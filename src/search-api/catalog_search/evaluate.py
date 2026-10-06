from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

from azure.core.exceptions import AzureError
from pydantic import BaseModel, ConfigDict, Field

from .app import public_product
from .config import DatabaseSettings
from .cosmos import CosmosRepository, connect
from .models import SearchRequest, ServiceError
from .query import build_query


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    request: SearchRequest
    grades: dict[str, int] = Field(default_factory=dict)
    expectedTotal: int | None = Field(default=None, ge=0)
    expectedIds: list[str] | None = None
    exhaustiveJudgments: bool = False


class EvaluationRow(BaseModel):
    case: str
    status: str
    elapsedMs: float
    requestUnits: float | None = None
    totalRecords: int | None = None
    records: list[str] = Field(default_factory=list)
    errorType: str | None = None
    ndcgAt10: float | None = None
    recallAt20: float | None = None


def quality(ids: list[str], grades: dict[str, int], exhaustive: bool) -> dict[str, float | None]:
    def dcg(values: list[int]) -> float:
        return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(values))

    ideal = dcg(sorted(grades.values(), reverse=True)[:10])
    ndcg = dcg([grades.get(item, 0) for item in ids[:10]]) / ideal if ideal else None
    relevant = {item for item, grade in grades.items() if grade > 0}
    recall = (
        len(relevant.intersection(ids[:20])) / len(relevant) if exhaustive and relevant else None
    )
    return {"ndcgAt10": ndcg, "recallAt20": recall}


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


async def evaluate(
    cases: list[EvaluationCase],
    settings: DatabaseSettings,
    scope: str,
    repeat: int,
    concurrency: int,
) -> dict[str, object]:
    semaphore = asyncio.Semaphore(concurrency)
    results: list[EvaluationRow] = []
    async with connect(settings) as container:
        repository = CosmosRepository(container, settings)
        await repository.ready(scope)

        async def run(case: EvaluationCase) -> None:
            async with semaphore:
                start = time.perf_counter()
                try:
                    async with asyncio.timeout(settings.deadline_seconds):
                        result = await repository.search(case.request, scope)
                    records = [
                        public_product(
                            doc,
                            case.request,
                            scope,
                            settings.import_epoch,
                            result.plan.identifier,
                            settings.image_base_url,
                        )
                        for doc in result.documents
                    ]
                    ids = [record.productId for record in records]
                    correct = (
                        case.expectedTotal is None or result.total == case.expectedTotal
                    ) and (case.expectedIds is None or ids == case.expectedIds)
                    metrics = quality(ids, case.grades, case.exhaustiveJudgments)
                    results.append(
                        EvaluationRow(
                            case=case.name,
                            status="passed" if correct else "failed",
                            elapsedMs=(time.perf_counter() - start) * 1000,
                            requestUnits=result.request_units,
                            totalRecords=result.total,
                            records=ids,
                            ndcgAt10=metrics["ndcgAt10"],
                            recallAt20=metrics["recallAt20"],
                        )
                    )
                except (ServiceError, TimeoutError) as error:
                    results.append(
                        EvaluationRow(
                            case=case.name,
                            status="error",
                            errorType=type(error).__name__,
                            elapsedMs=(time.perf_counter() - start) * 1000,
                        )
                    )

        await asyncio.gather(*(run(case) for _ in range(repeat) for case in cases))
    elapsed = [row.elapsedMs for row in results]
    failed = sum(row.status != "passed" for row in results)
    return {
        "evidence": "live-cosmos",
        "mode": "keyword",
        "importEpoch": settings.import_epoch,
        "requests": len(results),
        "concurrency": concurrency,
        "failedRequests": failed,
        "p50Ms": percentile(elapsed, 0.5),
        "p95Ms": percentile(elapsed, 0.95),
        "requestUnits": sum(row.requestUnits for row in results if row.requestUnits is not None),
        "failedRequestUnits": "not included when the SDK does not return response charges",
        "zeroResultRate": sum(row.totalRecords == 0 for row in results) / len(results),
        "notes": [
            "Latency/RU cover adapter count and ranked-prefix reads, not HTTP transport.",
            "Ready probe charges are excluded. Failure charges may be unavailable.",
            "Partial judgments cannot establish Recall@20; NDCG uses only supplied grades.",
            "No Google comparison or commercial uplift is implied.",
        ],
        "results": [row.model_dump() for row in results],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate query cases offline or run explicitly authorized Cosmos reads."
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--scope", default="demo-store")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if not 1 <= args.repeat <= 20 or not 1 <= args.concurrency <= 16:
            raise ValueError("repeat must be 1..20 and concurrency 1..16.")
        raw = json.loads(args.cases.read_text(encoding="utf-8"))
        if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
            raise ValueError("Cases must be a nonempty array with at most 100 entries.")
        cases = [EvaluationCase.model_validate(case) for case in raw]
        if any(grade < 0 or grade > 3 for case in cases for grade in case.grades.values()):
            raise ValueError("Relevance grades must be 0..3.")
        for case in cases:
            build_query(case.request, args.scope, "offline-validation")
        report: dict[str, object]
        if args.live:
            report = asyncio.run(
                evaluate(
                    cases, DatabaseSettings.from_env(), args.scope, args.repeat, args.concurrency
                )
            )
        else:
            report = {
                "evidence": "offline-case-validation-only",
                "cases": len(cases),
                "cloudReads": False,
            }
        if args.output:
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if report.get("failedRequests", 0):
            raise SystemExit(1)
    except (ValueError, OSError, KeyError, AzureError, TimeoutError, ServiceError) as error:
        print(
            f"Evaluation failed ({type(error).__name__}); verify cases, Cosmos configuration and authorization.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

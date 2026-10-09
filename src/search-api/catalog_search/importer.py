from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sqlite3
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from .catalog import CatalogDocument
from .config import DatabaseSettings
from .cosmos import FULL_TEXT_POLICY, IMPORT_MARKER, INDEXING_POLICY, connect, validate_container
from .models import ServiceError
from .staging import MAX_PRODUCTS, StagedCatalog, verify_image_manifest


class CatalogInput(Protocol):
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[CatalogDocument]: ...


def fingerprint(documents: CatalogInput) -> str:
    digest = hashlib.sha256()
    for index, doc in enumerate(documents):
        if index:
            digest.update(b"\n")
        digest.update(doc.model_dump_json(exclude_none=True).encode())
    return digest.hexdigest()


async def import_documents(
    documents: CatalogInput, settings: DatabaseSettings, *, workers: int = 1,
    max_request_units: float | None = None,
) -> dict[str, object]:
    if not 1 <= workers <= 8:
        raise ValueError("Import workers must be between 1 and 8.")
    if max_request_units is not None and (
        not math.isfinite(max_request_units) or max_request_units <= 0
    ):
        raise ValueError("Import RU allowance must be positive and finite.")
    charge = 0.0

    def response_hook(headers: Mapping[str, str], _: object) -> None:
        nonlocal charge
        if max_request_units is not None and "x-ms-request-charge" not in headers:
            raise ValueError("RU telemetry is missing; bounded import cannot continue.")
        charge += float(headers.get("x-ms-request-charge", "0"))

    def check_budget() -> None:
        if max_request_units is not None and charge >= max_request_units:
            raise ValueError("Import RU allowance reached; submitted operations may have completed.")
    first = next(iter(documents), None)
    if first is None or any(
        doc.scopeId != first.scopeId or doc.importEpoch != settings.import_epoch
        for doc in documents
    ):
        raise ValueError(
            "Import requires a nonempty, single-scope catalogue with the configured epoch."
        )
    scope = first.scopeId
    expected_hash = fingerprint(documents)
    async with connect(settings) as container:
        async with asyncio.timeout(settings.deadline_seconds):
            validate_container(await container.read())
            try:
                marker = await container.read_item(
                    IMPORT_MARKER, partition_key=scope, response_hook=response_hook
                )
            except CosmosResourceNotFoundError:
                marker = None
        if marker is not None and (
            marker.get("importEpoch") != settings.import_epoch
            or marker.get("contentSha256") != expected_hash
        ):
            raise ValueError(
                "Destination already contains a different import; use a fresh container."
            )
        ready = marker is not None and marker.get("status") == "ready"
        if marker is None:
            async with asyncio.timeout(settings.deadline_seconds):
                existing_counts = [
                    value
                    async for value in container.query_items(
                        "SELECT VALUE COUNT(1) FROM c WHERE c.scopeId = @scope",
                        parameters=[{"name": "@scope", "value": scope}],
                        partition_key=scope,
                        response_hook=response_hook,
                    )
                ]
                if existing_counts != [0]:
                    raise ValueError(
                        "Destination scope is not empty; use a fresh dedicated container."
                    )
            # A conditional create prevents two different imports claiming the same scope.
            async with asyncio.timeout(settings.deadline_seconds):
                check_budget()
                await container.create_item(
                    {
                        "id": IMPORT_MARKER,
                        "scopeId": scope,
                        "schemaVersion": "cosmos-import-v1",
                        "status": "importing",
                        "importEpoch": settings.import_epoch,
                        "contentSha256": expected_hash,
                    },
                    response_hook=response_hook,
                )
        async def import_one(document: CatalogDocument) -> None:
            async with asyncio.timeout(settings.deadline_seconds):
                check_budget()
                try:
                    existing = await container.read_item(
                        document.id, partition_key=scope, response_hook=response_hook
                    )
                except CosmosResourceNotFoundError:
                    existing = None
                if existing is not None:
                    if CatalogDocument.model_validate(existing) != document:
                        raise ValueError(
                            "Existing product differs from import; use a fresh container."
                        )
                elif ready:
                    raise ValueError(
                        "Published import is missing a product; do not repair in place."
                    )
                else:
                    check_budget()
                    await container.create_item(
                        document.model_dump(exclude_none=True), response_hook=response_hook
                    )
                check_budget()
                stored = await container.read_item(
                    document.id, partition_key=scope, response_hook=response_hook
                )
                if CatalogDocument.model_validate(stored) != document:
                    raise ValueError("Stored document verification failed.")
        pending = set()
        try:
            for document in documents:
                pending.add(asyncio.create_task(import_one(document)))
                if len(pending) >= workers:
                    completed, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
                    errors = [error for task in completed if (error := task.exception()) is not None]
                    if errors:
                        raise errors[0]
            if pending:
                await asyncio.gather(*pending)
        finally:
            if pending:
                # Drain submitted writes before closing the client; never publish on failure.
                await asyncio.gather(*pending, return_exceptions=True)
        async with asyncio.timeout(settings.deadline_seconds):
            check_budget()
            counts = [
                value
                async for value in container.query_items(
                    "SELECT VALUE COUNT(1) FROM c WHERE c.scopeId = @scope AND c.id != @marker",
                    parameters=[
                        {"name": "@scope", "value": scope},
                        {"name": "@marker", "value": IMPORT_MARKER},
                    ],
                    partition_key=scope,
                    response_hook=response_hook,
                )
            ]
            if counts != [len(documents)]:
                raise ValueError("Destination contains unexpected products.")
            summary = {
                "id": IMPORT_MARKER,
                "scopeId": scope,
                "schemaVersion": "cosmos-import-v1",
                "status": "ready",
                "importEpoch": settings.import_epoch,
                "contentSha256": expected_hash,
                "productCount": len(documents),
                "variantCount": sum(len(doc.variants) for doc in documents),
                "catalogSchemaVersion": first.schemaVersion,
            }
            if not ready:
                check_budget()
                await container.upsert_item(summary, response_hook=response_hook)
            return {**summary, "requestUnits": charge}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate/export a catalogue; writes require --write and --confirm-container."
    )
    parser.add_argument("--source", type=Path, default=Path("data") / "catalog" / "products.jsonl")
    parser.add_argument("--scope", default="demo-store")
    parser.add_argument("--area", default="storefront")
    parser.add_argument("--epoch", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--confirm-container")
    parser.add_argument("--max-products", type=int, default=MAX_PRODUCTS)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-request-units", type=float,
                        help="Stop scheduling at this observed RU allowance; in-flight calls can exceed it.")
    parser.add_argument("--capacity-reviewed", action="store_true",
                        help="Required for >1000-product writes after approved capacity/query preflight.")
    parser.add_argument(
        "--image-container", help="Publish v2 with relative container/blob image paths."
    )
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="catalog-validation-") as directory:
            documents = StagedCatalog(
                args.source, Path(directory) / "validated.sqlite", args.scope, args.area,
                args.epoch, args.image_container, args.max_products,
            )
            try:
                if args.output:
                    args.output.mkdir(parents=True, exist_ok=True)
                    product_path = args.output / "products.cosmos.jsonl"
                    if product_path.resolve() == args.source.resolve():
                        raise ValueError("Export must not overwrite the source catalogue.")
                    documents.export(product_path)
                    (args.output / "container-policy.json").write_text(
                        json.dumps({
                            "partitionKey": {"paths": ["/scopeId"], "kind": "Hash"},
                            "fullTextPolicy": FULL_TEXT_POLICY, "indexingPolicy": INDEXING_POLICY,
                        }, indent=2), encoding="utf-8",
                    )
                if args.write:
                    settings = DatabaseSettings.from_env()
                    if args.confirm_container != settings.container or args.epoch != settings.import_epoch:
                        raise ValueError(
                            "Confirm exact COSMOS_CONTAINER and matching CATALOG_IMPORT_EPOCH before writing."
                        )
                    manifest_path = args.source.parent / "manifest.json"
                    manifest = (
                        json.loads(manifest_path.read_text(encoding="utf-8"))
                        if manifest_path.exists() else {}
                    )
                    if len(documents) > 1000:
                        if not args.capacity_reviewed or args.max_request_units is None:
                            raise ValueError("Large import requires capacity review and an RU allowance.")
                    if len(documents) > 1000 or manifest.get("catalogVersion") == "synthetic-fashion-v2":
                        verify_image_manifest(args.source, documents, args.image_container)
                    summary = asyncio.run(import_documents(
                        documents, settings, workers=args.workers,
                        max_request_units=args.max_request_units,
                    ))
                else:
                    summary = documents.report()
            finally:
                documents.close()
        print(json.dumps(summary, indent=2))
    except (ValueError, OSError, KeyError, sqlite3.Error, AzureError, TimeoutError, ServiceError) as error:
        # SDK exception messages can contain endpoint details or payloads.
        print(
            f"Import failed ({type(error).__name__}); verify input, destination, index policy and authorization.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

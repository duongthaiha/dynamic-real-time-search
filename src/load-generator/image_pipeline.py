"""Capped MAI generation and verified Blob upload for an expanded catalogue."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import sqlite3
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from expand_catalog import (
    FIDELITY_PROMPT_VERSION,
    MAX_PRODUCTS,
    build_fashion_prompt,
    connect,
    run_lock,
    safe_source_path,
    summary,
)
from generate_images import (
    ContentBlocked,
    MaiClient,
    atomic_write,
    generation_spec,
    validate_png,
    write_json,
)


class Generator(Protocol):
    def generate(self, payload: dict[str, Any]) -> bytes: ...


class Publisher(Protocol):
    def publish(self, path: Path, name: str, sha256: str, md5: bytes) -> None: ...


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    def __init__(self, root: Path, name: str, limit: int):
        if not name or len(name) > 64 or not all(c.isalnum() or c in "-_." for c in name) or limit < 0:
            raise ValueError("An approval ID and nonnegative HTTP-request allowance are required")
        self.root, self.name = root, name
        self.local = threading.local()
        db = connect(root)
        try:
            with db:
                db.execute("INSERT OR IGNORE INTO budgets(name,limit_calls) VALUES(?,?)", (name, limit))
                existing = db.execute("SELECT limit_calls FROM budgets WHERE name=?", (name,)).fetchone()
                if existing[0] != limit:
                    raise ValueError("Approval allowance changed; request a new approval ID")
        finally:
            db.close()

    def spend(self) -> None:
        db = connect(self.root)
        try:
            with db:
                reserved = db.execute(
                    "UPDATE budgets SET used_calls=used_calls+1 WHERE name=? AND used_calls<limit_calls",
                    (self.name,),
                )
                if reserved.rowcount != 1:
                    raise BudgetExhausted("Approved HTTP-request allowance exhausted")
                db.execute(
                    "INSERT INTO attempts(product_id,budget,recorded_at,outcome) VALUES(?,?,?,?)",
                    (self.local.product_id, self.name, datetime.now(UTC).isoformat(), "submitted"),
                )
        finally:
            db.close()

    def record_response(self, receipt: dict[str, Any]) -> None:
        db = connect(self.root)
        try:
            with db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS responses("
                    "id INTEGER PRIMARY KEY,product_id TEXT NOT NULL,budget TEXT NOT NULL,receipt TEXT NOT NULL)"
                )
                db.execute(
                    "INSERT INTO responses(product_id,budget,receipt) VALUES(?,?,?)",
                    (self.local.product_id, self.name, json.dumps(receipt)),
                )
        finally:
            db.close()


def validate_image(data: bytes) -> tuple[str, bytes]:
    from PIL import Image

    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Image exceeds the 16 MiB staging limit")
    validate_png(data, 1024, 1024)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "PNG" or image.size != (1024, 1024):
            raise ValueError("Unexpected image format or size")
        image.load()
    return hashlib.sha256(data).hexdigest(), hashlib.md5(data, usedforsecurity=False).digest()


class BlobPublisher:
    def __init__(self, account: str, container: str):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        if not re.fullmatch(r"[a-z0-9]{3,24}", account):
            raise ValueError("Invalid Storage account name")
        if not 3 <= len(container) <= 63 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", container):
            raise ValueError("Invalid Blob container name")
        self.credential = DefaultAzureCredential()
        self.service = BlobServiceClient(
            f"https://{account}.blob.core.windows.net", credential=self.credential,
            retry_total=3, connection_timeout=15, read_timeout=60,
        )
        self.container = self.service.get_container_client(container)

    def close(self) -> None:
        self.service.close()
        self.credential.close()

    def publish(self, path: Path, name: str, sha256: str, md5: bytes) -> None:
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
        from azure.storage.blob import ContentSettings

        blob = self.container.get_blob_client(name)
        try:
            props = blob.get_blob_properties(timeout=60)
        except ResourceNotFoundError:
            try:
                with path.open("rb") as stream:
                    blob.upload_blob(
                        stream, length=path.stat().st_size, overwrite=False, validate_content=True,
                        metadata={"sha256": sha256},
                        content_settings=ContentSettings(content_type="image/png", content_md5=bytearray(md5)),
                        timeout=60,
                    )
            except ResourceExistsError:
                pass  # A previous upload may have committed before the connection failed.
            props = blob.get_blob_properties(timeout=60)
        if (
            props.size != path.stat().st_size or props.metadata.get("sha256") != sha256
            or bytes(props.content_settings.content_md5 or b"") != md5
            or props.content_settings.content_type != "image/png"
        ):
            raise ValueError(f"Blob integrity mismatch: {name}; existing content was not overwritten")


def mark(db: sqlite3.Connection, product_id: str, state: str, error: str | None = None) -> None:
    with db:
        db.execute("UPDATE products SET state=?,error=? WHERE product_id=?", (state, error, product_id))


def process_one(root: Path, row: sqlite3.Row, spec: dict[str, Any] | None,
                client: Generator, publisher: Publisher, budget: Budget) -> str:
    product_id = row["product_id"]
    budget.local.product_id = product_id
    db = connect(root)
    state = row["state"]
    stage = root / "staging" / f"{product_id.lower()}.png"
    receipt_path = stage.with_suffix(".json")
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest() if spec else None
    try:
        if row["fingerprint"] and row["fingerprint"] != fingerprint:
            raise ValueError("Generation inputs changed; a new catalogue is required")
        if state in {"submitted", "uncertain"}:
            if not stage.exists() or not receipt_path.exists():
                raise ValueError("Uncertain model outcome requires manual reconciliation; not resubmitted")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            digest, md5 = validate_image(stage.read_bytes())
            if receipt != {"fingerprint": fingerprint, "sha256": digest}:
                raise ValueError("Staging evidence differs from the submitted image job")
            with db:
                db.execute(
                    "UPDATE products SET state='staged',local_path=?,sha256=?,md5=?,image_bytes=? "
                    "WHERE product_id=?",
                    (stage.relative_to(root).as_posix(), digest, md5.hex(), stage.stat().st_size, product_id),
                )
            state = "staged"
        if state == "pending":
            if spec is None or stage.exists() or receipt_path.exists():
                raise ValueError("Unexpected staging state or missing generation specification")
            with db:
                db.execute(
                    "UPDATE products SET state='submitted',spec=?,fingerprint=? WHERE product_id=?",
                    (json.dumps(spec, sort_keys=True), fingerprint, product_id),
                )
            state = "submitted"
            data = client.generate(spec["payload"])
            digest, md5 = validate_image(data)
            write_json(receipt_path, {"fingerprint": fingerprint, "sha256": digest})
            atomic_write(stage, data)
            try:
                with db:
                    db.execute(
                        "UPDATE products SET state='staged',local_path=?,sha256=?,md5=?,image_bytes=? "
                        "WHERE product_id=?",
                        (stage.relative_to(root).as_posix(), digest, md5.hex(), len(data), product_id),
                    )
            except sqlite3.IntegrityError:
                mark(db, product_id, "duplicate", "Image checksum duplicates another product; review required")
                raise ValueError("Duplicate image output quarantined") from None
            state = "staged"
        if state != "staged":
            raise ValueError(f"Product is not eligible for generation/upload: {state}")
        current = db.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
        path = safe_source_path(root, current["local_path"])
        data = path.read_bytes()
        digest, md5 = validate_image(data)
        if digest != current["sha256"]:
            raise ValueError("Staged image checksum mismatch")
        name = f"{product_id.lower()}.png"
        publisher.publish(path, name, digest, md5)
        with db:
            db.execute(
                "UPDATE products SET state='verified',blob_name=?,md5=?,image_bytes=?,error=NULL,verified_at=? "
                "WHERE product_id=?", (name, md5.hex(), len(data), datetime.now(UTC).isoformat(), product_id),
            )
        if not current["original"]:
            path.unlink()
            receipt_path.unlink()
        return product_id
    except ContentBlocked:
        mark(db, product_id, "blocked", "Service safety block; review required, no automatic retry")
        raise
    except BudgetExhausted:
        count = db.execute(
            "SELECT COUNT(*) FROM attempts WHERE product_id=?", (product_id,),
        ).fetchone()[0]
        mark(db, product_id, "uncertain" if count else "pending", "Approved request allowance exhausted")
        raise
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        # Azure SDK errors are handled by run_batch; keep staged assets for upload-only resume.
        current = db.execute("SELECT state FROM products WHERE product_id=?", (product_id,)).fetchone()[0]
        if current == "submitted":
            attempted = db.execute(
                "SELECT EXISTS(SELECT 1 FROM attempts WHERE product_id=?)", (product_id,),
            ).fetchone()[0]
            mark(db, product_id, "uncertain" if attempted else "pending", type(error).__name__)
        raise
    finally:
        db.close()


def make_spec(product: dict[str, Any], deployment: str, version: str, endpoint: str) -> dict[str, Any]:
    spec = generation_spec(product, deployment, version, endpoint)
    spec["promptRevision"] = FIDELITY_PROMPT_VERSION
    spec["payload"]["prompt"] = build_fashion_prompt(product)
    return spec


def cleanup_verified_staging(root: Path, db: sqlite3.Connection) -> None:
    for path in (root / "staging").glob("*.png"):
        row = db.execute("SELECT * FROM products WHERE product_id=?", (path.stem.upper(),)).fetchone()
        if row is None or row["original"] or row["state"] != "verified":
            continue
        if safe_source_path(root, row["local_path"]) != path.resolve():
            raise ValueError("Verified staging path differs from its durable record")
        digest, _ = validate_image(path.read_bytes())
        if digest != row["sha256"]:
            raise ValueError("Verified staging content changed; not removed")
        path.unlink()
        path.with_suffix(".json").unlink(missing_ok=True)


def run_batch(root: Path, client: Generator, publisher: Publisher, budget: Budget, *,
              deployment: str, version: str, endpoint: str, start: int, end: int,
              max_products: int, workers: int, minimum_free_bytes: int = 1_073_741_824,
              pending_only: bool = False) -> dict[str, Any]:
    from azure.core.exceptions import AzureError

    if not 1 <= start <= end <= MAX_PRODUCTS or not 1 <= workers <= 8 or max_products < 1:
        raise ValueError("Invalid product range, product allowance or worker count")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", deployment) or not re.fullmatch(
        r"[A-Za-z0-9._-]{1,64}", version,
    ):
        raise ValueError("Use the actual deployment name and verified version, not placeholders")
    (root / "staging").mkdir(exist_ok=True)
    with run_lock(root):
        db = connect(root)
        try:
            cleanup_verified_staging(root, db)
            policy = json.dumps({"deployment": deployment, "version": version, "endpoint": endpoint},
                                sort_keys=True)
            with db:
                db.execute("INSERT OR IGNORE INTO settings VALUES('image-policy',?)", (policy,))
                if db.execute("SELECT value FROM settings WHERE key='image-policy'").fetchone()[0] != policy:
                    raise ValueError("Image deployment/version changed; use a separate catalogue")
            state_filter = (
                "state='pending' AND spec IS NULL AND fingerprint IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM attempts WHERE attempts.product_id=products.product_id)"
                if pending_only else "state IN ('pending','staged','submitted','uncertain')"
            )
            rows = iter(db.execute(
                "SELECT * FROM products WHERE ordinal BETWEEN ? AND ? "
                f"AND ({state_filter}) ORDER BY ordinal LIMIT ?",
                (start, end, max_products),
            ))
            if pending_only:
                print("Pending-only run: selecting unsubmitted jobs; existing blocked, uncertain, "
                      "staged and recorded-spec jobs remain untouched.", flush=True)
            failures = []
            blocked = 0
            stopped = False
            with ThreadPoolExecutor(max_workers=workers) as executor:
                pending = {}

                def submit() -> None:
                    if shutil.disk_usage(root).free < minimum_free_bytes:
                        raise OSError("Free disk space is below the configured staging safety reserve")
                    row = next(rows, None)
                    if row is not None:
                        spec = None
                        if not row["original"]:
                            spec = json.loads(row["spec"]) if row["spec"] else make_spec(
                                json.loads(row["payload"]), deployment, version, endpoint,
                            )
                        pending[executor.submit(process_one, root, row, spec, client, publisher, budget)] = row["product_id"]

                for _ in range(workers):
                    submit()
                while pending:
                    finished, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in finished:
                        product_id = pending.pop(future)
                        try:
                            future.result()
                        except ContentBlocked:
                            blocked += 1
                            print(f"BLOCKED {product_id}: review required", flush=True)
                        except (ValueError, OSError, RuntimeError, sqlite3.Error, AzureError) as error:
                            stopped = True
                            failures.append({"productId": product_id, "error": type(error).__name__})
                            print(f"FAILED {product_id}: {type(error).__name__}; inspect durable state", flush=True)
                        else:
                            print(f"VERIFIED {product_id}", flush=True)
                    if not stopped:
                        for _ in finished:
                            submit()
            result = summary(db)
            allowance = db.execute(
                "SELECT limit_calls,used_calls FROM budgets WHERE name=?", (budget.name,),
            ).fetchone()
            result.update(approvalId=budget.name, maximumHttpRequests=allowance[0],
                          submittedHttpRequests=allowance[1])
            result.update(batchFailures=failures, batchBlocked=blocked)
            result["selectionMode"] = "unsubmitted-only" if pending_only else "resume"
            result["unresolvedReviewCount"] = sum(
                result["states"].get(state, 0) for state in ("blocked", "uncertain", "duplicate")
            )
            write_json(root / "manifest.json", result)
            if failures or blocked:
                raise RuntimeError(f"Batch incomplete: {len(failures)} failures, {blocked} safety blocks")
            return result
        finally:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, required=True)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--deployment", default="MAI-Image-2.6-Flash")
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--requests-per-minute", type=int, default=6)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--start-id", type=int, default=1)
    parser.add_argument("--end-id", type=int, default=MAX_PRODUCTS)
    parser.add_argument("--max-products", type=int, default=1)
    parser.add_argument(
        "--pending-only", action="store_true",
        help="Select only pending jobs without recorded specs/attempts; do not retry or alter review jobs.",
    )
    parser.add_argument("--storage-account", required=True)
    parser.add_argument("--image-container", required=True)
    parser.add_argument("--approval-id", required=True)
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-storage")
    args = parser.parse_args()
    try:
        if not (args.catalog_dir / "catalog.sqlite").is_file():
            raise ValueError("An expanded catalogue is required")
        if not 1 <= args.requests_per_minute <= 60:
            raise ValueError("RPM must be in 1..60 and within the verified deployment allowance")
        if not args.execute:
            db = connect(args.catalog_dir)
            try:
                print(json.dumps({**summary(db), "cloudCalls": False, "approvalId": args.approval_id,
                                  "maximumHttpRequests": args.max_requests,
                                  "requestsPerMinute": args.requests_per_minute,
                                  "selectionMode": "unsubmitted-only" if args.pending_only else "resume"}, indent=2))
            finally:
                db.close()
            return
        if args.image_container == "product-images":
            raise ValueError("Use a new versioned image container, not the active product-images container")
        destination = f"{args.storage_account}/{args.image_container}"
        if args.confirm_storage != destination:
            raise ValueError("Confirm the exact Storage account/container before cloud writes")
        db = connect(args.catalog_dir)
        try:
            with db:
                db.execute("INSERT OR IGNORE INTO settings VALUES('destination',?)", (destination,))
                if db.execute("SELECT value FROM settings WHERE key='destination'").fetchone()[0] != destination:
                    raise ValueError("Destination changed; do not mix verified assets from different containers")
        finally:
            db.close()
        budget = Budget(args.catalog_dir, args.approval_id, args.max_requests)
        client = MaiClient(args.project_endpoint, args.requests_per_minute,
                           budget.spend, budget.record_response)
        publisher = BlobPublisher(args.storage_account, args.image_container)
        try:
            print(json.dumps(run_batch(
                args.catalog_dir, client, publisher, budget, deployment=args.deployment,
                version=args.model_version, endpoint=args.project_endpoint, start=args.start_id,
                end=args.end_id, max_products=args.max_products, workers=args.workers,
                pending_only=args.pending_only,
            ), indent=2))
        finally:
            publisher.close()
    except (ValueError, OSError, RuntimeError, sqlite3.Error, KeyError) as error:
        parser.exit(1, f"Image pipeline failed: {error}\n")


if __name__ == "__main__":
    main()

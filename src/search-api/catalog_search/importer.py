from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError

from .catalog import CatalogDocument, load_catalog
from .config import DatabaseSettings
from .cosmos import FULL_TEXT_POLICY, IMPORT_MARKER, INDEXING_POLICY, connect, validate_container
from .models import ServiceError


def fingerprint(documents: list[CatalogDocument]) -> str:
    payload = "\n".join(doc.model_dump_json(exclude_none=True) for doc in documents)
    return hashlib.sha256(payload.encode()).hexdigest()


async def import_documents(
    documents: list[CatalogDocument], settings: DatabaseSettings
) -> dict[str, object]:
    if not documents or any(
        doc.scopeId != documents[0].scopeId or doc.importEpoch != settings.import_epoch
        for doc in documents
    ):
        raise ValueError(
            "Import requires a nonempty, single-scope catalogue with the configured epoch."
        )
    scope = documents[0].scopeId
    expected_hash = fingerprint(documents)
    async with connect(settings) as container:
        async with asyncio.timeout(settings.deadline_seconds):
            validate_container(await container.read())
            try:
                marker = await container.read_item(IMPORT_MARKER, partition_key=scope)
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
                    )
                ]
                if existing_counts != [0]:
                    raise ValueError(
                        "Destination scope is not empty; use a fresh dedicated container."
                    )
            # A conditional create prevents two different imports claiming the same scope.
            async with asyncio.timeout(settings.deadline_seconds):
                await container.create_item(
                    {
                        "id": IMPORT_MARKER,
                        "scopeId": scope,
                        "schemaVersion": "cosmos-import-v1",
                        "status": "importing",
                        "importEpoch": settings.import_epoch,
                        "contentSha256": expected_hash,
                    }
                )
        for document in documents:
            async with asyncio.timeout(settings.deadline_seconds):
                try:
                    existing = await container.read_item(document.id, partition_key=scope)
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
                    await container.create_item(document.model_dump(exclude_none=True))
                stored = await container.read_item(document.id, partition_key=scope)
                if CatalogDocument.model_validate(stored) != document:
                    raise ValueError("Stored document verification failed.")
        async with asyncio.timeout(settings.deadline_seconds):
            counts = [
                value
                async for value in container.query_items(
                    "SELECT VALUE COUNT(1) FROM c WHERE c.scopeId = @scope AND c.id != @marker",
                    parameters=[
                        {"name": "@scope", "value": scope},
                        {"name": "@marker", "value": IMPORT_MARKER},
                    ],
                    partition_key=scope,
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
                "catalogSchemaVersion": documents[0].schemaVersion,
            }
            if not ready:
                await container.upsert_item(summary)
            return summary


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
    parser.add_argument(
        "--image-container", help="Publish v2 with relative container/blob image paths."
    )
    args = parser.parse_args()
    try:
        documents = load_catalog(
            args.source, args.scope, args.area, args.epoch, args.image_container
        )
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True)
            product_path = args.output / "products.cosmos.jsonl"
            if product_path.resolve() == args.source.resolve():
                raise ValueError("Export must not overwrite the source catalogue.")
            product_path.write_text(
                "\n".join(doc.model_dump_json(exclude_none=True) for doc in documents) + "\n",
                encoding="utf-8",
            )
            (args.output / "container-policy.json").write_text(
                json.dumps(
                    {
                        "partitionKey": {"paths": ["/scopeId"], "kind": "Hash"},
                        "fullTextPolicy": FULL_TEXT_POLICY,
                        "indexingPolicy": INDEXING_POLICY,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        if args.write:
            settings = DatabaseSettings.from_env()
            if args.confirm_container != settings.container or args.epoch != settings.import_epoch:
                raise ValueError(
                    "Confirm exact COSMOS_CONTAINER and matching CATALOG_IMPORT_EPOCH before writing."
                )
            summary = asyncio.run(import_documents(documents, settings))
        else:
            summary = {
                "status": "offline-validated",
                "productCount": len(documents),
                "variantCount": sum(len(doc.variants) for doc in documents),
                "contentSha256": fingerprint(documents),
                "cloudWrites": False,
            }
        print(json.dumps(summary, indent=2))
    except (ValueError, OSError, KeyError, AzureError, TimeoutError, ServiceError) as error:
        # SDK exception messages can contain endpoint details or payloads.
        print(
            f"Import failed ({type(error).__name__}); verify input, destination, index policy and authorization.",
            file=sys.stderr,
        )
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()

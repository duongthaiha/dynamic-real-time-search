"""Disk-backed, fully validated snapshots for bounded-memory catalogue imports."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

from .catalog import CatalogDocument, map_product

MAX_PRODUCTS = 2_000_000
MAX_LINE_BYTES = 262144
DOCUMENT_BUDGET_BYTES = 10 * 1024**3


class StagedCatalog:
    def __init__(self, source: Path, database: Path, scope: str, area: str, epoch: str,
                 image_container: str | None = None, max_products: int = MAX_PRODUCTS):
        if database.exists():
            raise ValueError("Validation staging database must be new.")
        if not 1 <= max_products <= MAX_PRODUCTS:
            raise ValueError("Catalogue limit must be between 1 and 2,000,000.")
        self.db = sqlite3.connect(database)
        self.count = 0
        self.variant_count = 0
        self.document_bytes = 0
        self.maximum_document_bytes = 0
        self.source_sha256 = ""
        self.content_sha256 = ""
        try:
            self.db.executescript("""
                CREATE TABLE documents (
                    ordinal INTEGER PRIMARY KEY, id TEXT UNIQUE, colourway TEXT UNIQUE, payload TEXT
                );
                CREATE TABLE skus (sku TEXT PRIMARY KEY, variant_id TEXT UNIQUE);
            """)
            source_hash, content_hash = hashlib.sha256(), hashlib.sha256()
            with source.open("rb") as stream:
                with self.db:
                    while line := stream.readline(MAX_LINE_BYTES + 1):
                        line_number = self.count + 1
                        if len(line) > MAX_LINE_BYTES or line_number > max_products:
                            raise ValueError("Catalogue exceeds its product or 256 KiB record limit.")
                        source_hash.update(line)
                        try:
                            raw = json.loads(line, parse_float=Decimal)
                            if not isinstance(raw, dict):
                                raise ValueError("Product must be an object.")
                            doc = map_product(raw, scope, area, epoch, image_container)
                            payload = doc.model_dump_json(exclude_none=True)
                            self.db.execute("INSERT INTO documents VALUES(?,?,?,?)",
                                            (line_number, doc.id, doc.colourWayId, payload))
                            self.db.executemany("INSERT INTO skus VALUES(?,?)",
                                                ((v.sku, v.variantId) for v in doc.variants))
                        except (ValueError, KeyError, TypeError, sqlite3.IntegrityError) as error:
                            raise ValueError(f"Invalid catalogue record at line {line_number}.") from error
                        encoded = payload.encode()
                        if self.count:
                            content_hash.update(b"\n")
                        content_hash.update(encoded)
                        self.count += 1
                        self.variant_count += len(doc.variants)
                        self.document_bytes += len(encoded)
                        self.maximum_document_bytes = max(self.maximum_document_bytes, len(encoded))
                        if self.document_bytes > DOCUMENT_BUDGET_BYTES:
                            raise ValueError("Single-partition document-data planning budget exceeded.")
            if not self.count:
                raise ValueError("Catalogue is empty.")
            self.source_sha256 = source_hash.hexdigest()
            self.content_sha256 = content_hash.hexdigest()
        except (ValueError, OSError, sqlite3.Error):
            self.db.close()
            raise

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[CatalogDocument]:
        for (payload,) in self.db.execute("SELECT payload FROM documents ORDER BY ordinal"):
            yield CatalogDocument.model_validate_json(payload)

    def close(self) -> None:
        self.db.close()

    def report(self) -> dict[str, object]:
        return {
            "status": "offline-validated", "productCount": self.count,
            "variantCount": self.variant_count, "sourceSha256": self.source_sha256,
            "contentSha256": self.content_sha256, "documentBytes": self.document_bytes,
            "maximumDocumentBytes": self.maximum_document_bytes,
            "documentBudgetBytes": DOCUMENT_BUDGET_BYTES,
            "indexOverheadIncluded": False, "cloudWrites": False,
        }

    def export(self, path: Path) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            for (payload,) in self.db.execute("SELECT payload FROM documents ORDER BY ordinal"):
                stream.write(payload + "\n")
        temporary.replace(path)


def verify_image_manifest(source: Path, catalog: StagedCatalog, image_container: str | None) -> None:
    manifest = json.loads((source.parent / "manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("ready") is not True or manifest.get("metadataOnly") is not False
        or manifest.get("contentSha256") != catalog.source_sha256
        or manifest.get("productCount") != len(catalog)
        or manifest.get("states") != {"verified": len(catalog)}
        or not image_container
        or not str(manifest.get("imageDestination", "")).endswith("/" + image_container)
    ):
        raise ValueError("Expanded catalogue requires a matching fully image-verified export manifest.")

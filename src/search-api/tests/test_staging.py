from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_search import EPOCH, SCOPE, document, request, source

from catalog_search.importer import fingerprint
from catalog_search.query import build_query
from catalog_search.staging import StagedCatalog, verify_image_manifest


class StagingTests(unittest.TestCase):
    def test_disk_backed_validation_preserves_legacy_fingerprint(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "input.jsonl"
            path.write_text(json.dumps(source(), default=float) + "\n")
            staged = StagedCatalog(path, root / "stage.sqlite", SCOPE, "storefront", EPOCH)
            try:
                self.assertEqual(len(staged), 1)
                self.assertEqual(list(staged), [document()])
                self.assertEqual(staged.content_sha256, fingerprint([document()]))
                self.assertEqual(staged.content_sha256, fingerprint(staged))
                self.assertGreater(staged.document_bytes, 0)
                staged.export(root / "normalized.jsonl")
                self.assertEqual(json.loads((root / "normalized.jsonl").read_text()),
                                 document().model_dump(exclude_none=True))
            finally:
                staged.close()

    def test_invalid_duplicate_and_oversized_records_fail_before_import(self):
        for variant in ("duplicate", "oversized", "limit"):
            with self.subTest(variant=variant), TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "input.jsonl"
                line = json.dumps(source(), default=float) + "\n"
                path.write_text(" " * 262145 if variant == "oversized" else line * 2)
                with self.assertRaises(ValueError):
                    StagedCatalog(path, root / "stage.sqlite", SCOPE, "storefront", EPOCH,
                                  max_products=1 if variant == "limit" else 2_000_000)

    def test_large_identifiers_retain_exact_lookup(self):
        for number in (999999, 1000000, 2000000):
            for identifier in (f"PROD-{number}", f"SYN-{number}-01"):
                with self.subTest(identifier=identifier):
                    plan = build_query(request(query=identifier.lower()), SCOPE, EPOCH)
                    self.assertEqual(plan.identifier, identifier)
                    self.assertNotIn("FullTextContainsAll", plan.records_sql)
        for identifier in ("PROD-2000001", "PROD-000000", "SYN-2000001-01", "PROD-01000000"):
            self.assertIsNone(build_query(request(query=identifier), SCOPE, EPOCH).identifier)

    def test_metadata_only_exports_cannot_be_published(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "input.jsonl"
            path.write_text(json.dumps(source(), default=float) + "\n")
            staged = StagedCatalog(path, root / "stage.sqlite", SCOPE, "storefront", EPOCH)
            try:
                manifest = {
                    "ready": True, "metadataOnly": False, "productCount": 1,
                    "contentSha256": staged.source_sha256, "states": {"verified": 1},
                    "imageDestination": "account/product-images-scale-001",
                }
                (root / "manifest.json").write_text(json.dumps(manifest))
                verify_image_manifest(path, staged, "product-images-scale-001")
                manifest["metadataOnly"] = True
                (root / "manifest.json").write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "image-verified"):
                    verify_image_manifest(path, staged, "product-images-scale-001")
            finally:
                staged.close()


if __name__ == "__main__":
    unittest.main()

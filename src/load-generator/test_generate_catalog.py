import json
import tempfile
import unittest
from pathlib import Path

from generate_catalog import generate_catalog


class GenerateCatalogTests(unittest.TestCase):
    def test_generates_deterministic_index_ready_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_dir = Path(first)
            second_dir = Path(second)

            first_manifest = generate_catalog(first_dir, 31, 42, "https://images.example.test", 10)
            second_manifest = generate_catalog(second_dir, 31, 42, "https://images.example.test", 10)

            self.assertEqual(first_manifest["productCount"], 31)
            self.assertEqual(first_manifest["imageCount"], 31)
            self.assertEqual(first_manifest["searchBatchCount"], 4)
            self.assertEqual(
                (first_dir / "products.jsonl").read_bytes(),
                (second_dir / "products.jsonl").read_bytes(),
            )

            products = [
                json.loads(line)
                for line in (first_dir / "products.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len({product["productId"] for product in products}), 31)
            self.assertTrue(all(product["variants"] for product in products))
            self.assertTrue(all(product["isInStock"] for product in products))
            self.assertTrue(all(product["trendingScore"] == 0 for product in products))
            self.assertTrue(all((first_dir / product["imagePath"]).is_file() for product in products))

            batch = json.loads(
                (first_dir / "azure-search-batches" / "batch-0001.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(batch["value"]), 10)
            self.assertTrue(all(document["@search.action"] == "upload" for document in batch["value"]))
            self.assertTrue(all(len(document["trendStateVersion"]) == 20 for document in batch["value"]))

            index = json.loads(
                (Path(__file__).parent / "azure-search-index.json").read_text(encoding="utf-8")
            )
            fields = {field["name"]: field for field in index["fields"]}
            document_fields = set(batch["value"][0]) - {"@search.action"}
            self.assertEqual(document_fields, set(fields))
            self.assertFalse(
                any(
                    field.get("sortable")
                    for field in index["fields"]
                    if field["type"].startswith("Collection(")
                )
            )

    def test_rejects_invalid_generation_limits(self) -> None:
        with tempfile.TemporaryDirectory() as output:
            with self.assertRaisesRegex(ValueError, "count"):
                generate_catalog(Path(output), 0, 42, "https://images.example.test", 100)
            with self.assertRaisesRegex(ValueError, "batch-size"):
                generate_catalog(Path(output), 1, 42, "https://images.example.test", 0)


if __name__ == "__main__":
    unittest.main()

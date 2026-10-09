import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from generate_catalog import generate_catalog
from generate_search_terms import QUOTAS, build_terms, read_products, write_dataset


class SearchTermTests(unittest.TestCase):
    def test_exact_count_coverage_and_reproducibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog"
            generate_catalog(catalog, 1000, 20260924, "https://example.test", 100)
            source = catalog / "products.jsonl"
            original = source.read_bytes()
            products = read_products(source)
            first = write_dataset(source, root / "first")
            second = write_dataset(source, root / "second")
            self.assertEqual(first, second)
            self.assertEqual(source.read_bytes(), original)
            with (root / "first" / "search-terms.csv").open(
                encoding="utf-8", newline="",
            ) as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1000)
            self.assertEqual(len({row["query"].casefold() for row in rows}), 1000)
            self.assertEqual(len({row["queryId"] for row in rows}), 1000)
            self.assertEqual(Counter(row["intent"] for row in rows), Counter(QUOTAS))
            self.assertEqual({p.category for p in products},
                             {row["category"] for row in rows} - {"service"})
            self.assertTrue(all(row["query"] == " ".join(row["query"].split()) for row in rows))
            self.assertTrue(all(0 < len(row["query"]) <= 200 for row in rows))
            heads = {p.category if p.category != "accessories" else "caps" for p in products}
            self.assertTrue(heads <= {row["query"] for row in rows})
            self.assertFalse(any("beanie caps" in row["query"] for row in rows))
            self.assertFalse(any("fabric skirts" in row["query"] for row in rows
                                 if row["intent"] == "feature"))
            self.assertEqual(
                (root / "first" / "search-terms.txt").read_text().splitlines(),
                [row["query"] for row in rows],
            )
            exact = [row["query"] for row in rows if row["intent"] == "exact"]
            self.assertEqual(sum(q.startswith("prod-") for q in exact), 20)
            self.assertEqual(sum(q.startswith("syn-") for q in exact), 20)
            known = {p.product_id.lower() for p in products}
            known.update(p.title.lower() for p in products)
            known.update(sku.lower() for p in products for sku in p.skus)
            self.assertTrue(set(exact) <= known)
            batches = sorted((root / "first" / "evaluation-batches").glob("*.json"))
            self.assertEqual(len(batches), 10)
            cases = [case for batch in batches for case in json.loads(batch.read_text())]
            self.assertTrue(all(len(json.loads(batch.read_text())) == 100 for batch in batches))
            self.assertEqual([case["request"]["query"] for case in cases],
                             [row["query"] for row in rows])
            self.assertTrue(all(set(case) == {"name", "request"} for case in cases))
            self.assertNotEqual(build_terms(products, 1), build_terms(products, 2))
            file_metadata = first["files"]
            assert isinstance(file_metadata, dict)
            for relative, metadata in file_metadata.items():
                content = (root / "first" / relative).read_bytes()
                self.assertEqual(metadata["sha256"], hashlib.sha256(content).hexdigest())
                self.assertEqual(content, (root / "second" / relative).read_bytes())

    def test_repeatable_across_processes_and_ignores_unrelated_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog"
            generate_catalog(catalog, 1000, 20260924, "https://example.test", 100)
            for name, hash_seed in (("first", "1"), ("second", "2")):
                output = root / name
                output.mkdir()
                (output / "unrelated.txt").write_text(name)
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name("generate_search_terms.py")),
                     "--source", str(catalog / "products.jsonl"), "--output", str(output)],
                    env={**os.environ, "PYTHONHASHSEED": hash_seed},
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((output / "unrelated.txt").read_text(), name)
            self.assertEqual(
                (root / "first" / "manifest.json").read_bytes(),
                (root / "second" / "manifest.json").read_bytes(),
            )
            self.assertEqual(
                (root / "first" / "search-terms.csv").read_bytes(),
                (root / "second" / "search-terms.csv").read_bytes(),
            )

    def test_rejects_invalid_source_and_insufficient_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "products.jsonl"
            for invalid in ("", "[]\n", "{}\n", '{"variants": [null]}\n'):
                source.write_text(invalid, encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_products(source)
            with self.assertRaisesRegex(ValueError, "distinct candidates"):
                build_terms([])


if __name__ == "__main__":
    unittest.main()

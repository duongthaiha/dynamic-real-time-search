import copy
import io
import json
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from generate_catalog import generate_catalog
from generate_images import ContentBlocked, MaiClient, atomic_write, generate_one, generation_spec, image_endpoint, reviewed_spec, synchronize, validate_png


ENDPOINT = "https://test.services.ai.azure.com/api/projects/demo"


def png_bytes() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", 1024, 1024, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(1025 * 1024))) + chunk(b"IEND", b"")
    )


class GenerateImagesTests(unittest.TestCase):
    def test_reviewed_prompt_is_category_specific(self) -> None:
        from generate_catalog import build_product
        import random
        for index in range(1, 16):
            product, _, _ = build_product(index, random.Random(42), "https://images.example.test")
            prompt = reviewed_spec(product, "mai", "v1", ENDPOINT)["payload"]["prompt"]
            self.assertIn(product["colourName"], prompt)
            self.assertIn(product["material"], prompt)
            self.assertIn(product["fit"], prompt)
            self.assertEqual("pair of shoes" in prompt, product["category"] in {"boots", "trainers"})
            self.assertNotIn("Trousers have", prompt)

    def test_reviewed_pass_preserves_history_and_resumes_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_catalog(root, 2, 42, "https://images.example.test", 1)
            (root / "image-generation").mkdir()
            products = [json.loads(line) for line in (root / "products.jsonl").read_text().splitlines()]
            product = products[0]
            old_block = root / "image-generation" / "prod-000001.blocked.json"
            old_block.write_text('{"reason": "original service block"}')
            original = old_block.read_bytes()
            spec = reviewed_spec(product, "mai", "v1", ENDPOINT)
            client = Mock()
            client.generate.return_value = png_bytes()
            receipt = generate_one(root, product, spec, client)
            self.assertEqual(generate_one(root, product, spec, client), receipt)
            client.generate.assert_called_once()
            synchronize(root, products, {product["productId"]: receipt})
            self.assertEqual(old_block.read_bytes(), original)
            self.assertEqual(json.loads((root / "manifest.json").read_text())["blockedImageCount"], 0)
            self.assertTrue(product["imagePath"].endswith(".png"))
            with self.assertRaisesRegex(ValueError, "original block"):
                generate_one(root, products[1], reviewed_spec(products[1], "mai", "v1", ENDPOINT), client)

    def test_reviewed_block_and_uncertain_attempt_are_not_resubmitted(self) -> None:
        for failure in (ContentBlocked("Service block"), OSError("Connection lost")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                generate_catalog(root, 1, 42, "https://images.example.test", 1)
                (root / "image-generation").mkdir()
                original = root / "image-generation" / "prod-000001.blocked.json"
                original.write_text('{"reason": "original block"}')
                product = json.loads((root / "products.jsonl").read_text())
                spec = reviewed_spec(product, "mai", "v1", ENDPOINT)
                client = Mock()
                client.generate.side_effect = failure
                with self.assertRaises(type(failure)):
                    generate_one(root, product, spec, client)
                with self.assertRaises((ContentBlocked, ValueError)):
                    generate_one(root, product, spec, client)
                client.generate.assert_called_once()
                self.assertEqual(original.read_text(), '{"reason": "original block"}')

    def test_transient_file_lock_and_unchanged_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.json"
            original_replace = Path.replace
            attempts = []

            def locked_once(source, target):
                attempts.append(target)
                if len(attempts) == 1:
                    raise PermissionError("File locked")
                return original_replace(source, target)

            with patch.object(Path, "replace", locked_once), patch("generate_images.time.sleep"):
                atomic_write(path, b"sample")
                atomic_write(path, b"sample")
            self.assertEqual(path.read_bytes(), b"sample")
            self.assertEqual(len(attempts), 2)

    def test_endpoint_validation(self) -> None:
        self.assertEqual(image_endpoint(ENDPOINT), "https://test.services.ai.azure.com/mai/v1/images/generations")
        for bad in ("http://test.services.ai.azure.com", "https://example.com", ENDPOINT + "?key=secret"):
            with self.assertRaises(ValueError):
                image_endpoint(bad)

    def test_png_validation(self) -> None:
        data = png_bytes()
        validate_png(data, 1024, 1024)
        for invalid in (b"not an image", data[:-12], data[:42] + b"X" + data[43:]):
            with self.assertRaises(ValueError):
                validate_png(invalid, 1024, 1024)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            validate_png(data, 768, 768)

    def test_resume_synchronize_and_protect_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_catalog(root, 2, 42, "https://images.example.test", 1)
            (root / "image-generation").mkdir()
            products = [json.loads(line) for line in (root / "products.jsonl").read_text().splitlines()]
            original = copy.deepcopy(products)
            batch_path = root / "azure-search-batches" / "batch-0001.json"
            batch = json.loads(batch_path.read_text())
            batch["value"][0]["trendingScore"] = 42
            batch_path.write_text(json.dumps(batch))
            spec = generation_spec(products[0], "MAI-Image-2.6", "2026-07-31", ENDPOINT)
            self.assertIn(products[0]["description"], spec["payload"]["prompt"])
            client = Mock()
            client.generate.return_value = png_bytes()
            first = generate_one(root, products[0], spec, client)
            self.assertEqual(generate_one(root, products[0], spec, client), first)
            client.generate.assert_called_once()
            synchronize(root, products, {products[0]["productId"]: first})
            self.assertTrue(products[0]["imagePath"].endswith(".png"))
            self.assertEqual(products[0]["images"][0]["url"], products[0]["imageUrl"])
            self.assertEqual(products[1], original[1])
            for field in set(products[0]) - {"imagePath", "imageUrl", "images"}:
                self.assertEqual(products[0][field], original[0][field])
            updated_batch = json.loads(batch_path.read_text())
            self.assertEqual(updated_batch["value"][0]["imageUrl"], products[0]["imageUrl"])
            self.assertEqual(updated_batch["value"][0]["trendingScore"], 42)
            self.assertTrue((root / "images" / "prod-000001.svg").exists())
            with self.assertRaisesRegex(ValueError, "different output"):
                generate_catalog(root, 2, 42, "https://images.example.test", 1)
            changed = copy.deepcopy(spec)
            changed["payload"]["prompt"] += " changed"
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                generate_one(root, products[0], changed, client)
            (root / first["imagePath"]).write_bytes(b"broken")
            with self.assertRaises(ValueError):
                generate_one(root, products[0], spec, client)

    def test_failures_do_not_publish_or_retry_uncertain_requests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_catalog(root, 1, 42, "https://images.example.test", 1)
            (root / "image-generation").mkdir()
            product = json.loads((root / "products.jsonl").read_text())
            client = Mock()
            client.generate.side_effect = RuntimeError("generation failed")
            with self.assertRaisesRegex(RuntimeError, "generation failed"):
                generate_one(root, product, generation_spec(product, "mai", "v1", ENDPOINT), client)
            self.assertFalse((root / "images" / "prod-000001.png").exists())
            self.assertTrue(product["imagePath"].endswith(".svg"))
        with patch("generate_images.AzureCliToken") as token, patch("generate_images.urlopen") as request:
            token.return_value.get.return_value = "test-token"
            request.side_effect = HTTPError(ENDPOINT, 503, "Unavailable", {}, None)
            client = MaiClient(ENDPOINT, 6)
            with self.assertRaisesRegex(RuntimeError, "HTTP 503"):
                client.generate({})
            self.assertEqual(request.call_count, 1)

    def test_throttling_is_bounded(self) -> None:
        with patch("generate_images.AzureCliToken"), patch("generate_images.urlopen") as request, patch("generate_images.time.sleep"):
            request.side_effect = HTTPError(ENDPOINT, 429, "Throttled", {"Retry-After": "1"}, None)
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                MaiClient(ENDPOINT, 6).generate({})
            self.assertEqual(request.call_count, 5)

    def test_content_block_is_recorded_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generate_catalog(root, 1, 42, "https://images.example.test", 1)
            (root / "image-generation").mkdir()
            product = json.loads((root / "products.jsonl").read_text())
            spec = generation_spec(product, "mai", "v1", ENDPOINT)
            client = Mock()
            client.generate.side_effect = ContentBlocked("Service refused image")
            for _ in range(2):
                with self.assertRaises(ContentBlocked):
                    generate_one(root, product, spec, client)
            client.generate.assert_called_once()
            synchronize(root, [product], {})
            self.assertEqual(json.loads((root / "manifest.json").read_text())["blockedImageCount"], 1)
            self.assertTrue(product["imagePath"].endswith(".svg"))

    def test_authentication_refresh_is_bounded(self) -> None:
        with patch("generate_images.AzureCliToken") as token, patch("generate_images.urlopen") as request, patch("generate_images.time.sleep"):
            request.side_effect = HTTPError(ENDPOINT, 401, "Unauthorized", {}, None)
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                MaiClient(ENDPOINT, 6).generate({})
            self.assertEqual(request.call_count, 2)
            token.return_value.invalidate.assert_called_once()

    def test_only_confirmed_unsent_connection_errors_are_retried(self) -> None:
        with patch("generate_images.AzureCliToken"), patch("generate_images.urlopen") as request, patch("generate_images.time.sleep"):
            body = b'{"error":{"code":"client_connection_closed","message":"Client has closed connection before request was sent."}}'
            request.side_effect = [
                HTTPError(ENDPOINT, 499, "Closed", {}, io.BytesIO(body)),
                HTTPError(ENDPOINT, 499, "Unknown outcome", {}, io.BytesIO(b"Unknown outcome")),
            ]
            with self.assertRaisesRegex(RuntimeError, "HTTP 499"):
                MaiClient(ENDPOINT, 6).generate({})
            self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()

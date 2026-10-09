import base64
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from expand_catalog import (
    FIDELITY_PROMPT_VERSION,
    PATTERN_INSTRUCTIONS,
    PROMPT_VERSION,
    TYPES,
    build_fashion_prompt,
    capacity,
    connect,
    expand,
    export,
    fashion_product,
)
from generate_catalog import generate_catalog
from generate_images import (
    ContentBlocked,
    MaiClient,
    generate_one,
    generation_spec,
    synchronize,
)
from image_pipeline import (
    BlobPublisher,
    Budget,
    BudgetExhausted,
    cleanup_verified_staging,
    make_spec,
    process_one,
    run_batch,
    validate_image,
)
from PIL import Image

ENDPOINT = "https://test.services.ai.azure.com/api/projects/offline"


def image_bytes(colour=100):
    stream = io.BytesIO()
    Image.new("RGB", (1024, 1024), (colour, 30, 70)).save(stream, format="PNG")
    return stream.getvalue()


def original_catalog(root: Path):
    generate_catalog(root, 1, 42, "https://images.example.test", 1)
    (root / "image-generation").mkdir()
    product = json.loads((root / "products.jsonl").read_text())
    client = Mock()
    client.generate.return_value = image_bytes(1)
    receipt = generate_one(root, product, generation_spec(product, "original", "v1", ENDPOINT), client)
    synchronize(root, [product], {product["productId"]: receipt})


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "source"
        self.root = Path(self.directory.name) / "expanded"
        original_catalog(self.source)

    def test_preserves_originals_and_resumes_without_changes(self):
        before = (self.source / "products.jsonl").read_bytes()
        first = expand(self.source, self.root, 84, 42)
        second = expand(self.source, self.root, 84, 42)
        self.assertEqual(first, second)
        self.assertEqual(first["productCount"], 84)
        self.assertEqual(first["states"], {"pending": 83, "staged": 1})
        self.assertEqual((self.source / "products.jsonl").read_bytes(), before)
        self.assertEqual((self.root / "original" / "products.jsonl").read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            expand(self.source, self.root, 84, 43)
        with self.assertRaisesRegex(ValueError, "Every image"):
            export(self.root, self.root / "export")
        report = export(self.root, self.root / "metadata", metadata_only=True)
        self.assertTrue(report["metadataOnly"])
        self.assertFalse(report["ready"])
        self.assertEqual(len((self.root / "metadata" / "products.jsonl").read_text().splitlines()), 84)
        prompts = (self.root / "metadata" / "image-prompts.jsonl").read_text().splitlines()
        self.assertEqual(len(prompts), 83)
        first_prompt = json.loads(prompts[0])
        expected, _ = fashion_product(2, 0, 42, "https://cdn.example.com/synthetic-products")
        self.assertEqual(first_prompt["prompt"], build_fashion_prompt(expected))
        self.assertEqual(first_prompt["targetFile"], "images/prod-000002.png")

    def test_distinct_coherent_designs_and_balanced_presentations(self):
        self.assertGreaterEqual(capacity(), 2_000_000)
        signatures = set()
        per_category = {}
        for ordinal in range(len(TYPES) * 6):
            product, signature = fashion_product(1001 + ordinal, ordinal, 42, "https://test.example")
            self.assertNotIn(signature, signatures)
            signatures.add(signature)
            self.assertTrue(all(v["colour"] == product["colourName"] for v in product["variants"]))
            policy = product["photography"]
            per_category.setdefault(product["category"], []).append(policy["adultModel"])
            prompt = build_fashion_prompt(product)
            for fact in ("productType", "fit", "material", "colourName", "colourHex", "pattern", "accent"):
                self.assertIn(product[fact], prompt)
            self.assertEqual("No people." in prompt, policy["presentation"] == "product-only")
            if policy["presentation"] == "modelled":
                self.assertIn("age 25 or older", prompt)
        for values in per_category.values():
            self.assertEqual(sorted(values.count(v) for v in set(values)), [2, 2, 2])
        for index in (999999, 1000000, 2000000):
            product, _ = fashion_product(index, index - 1001, 42, "https://test.example")
            self.assertEqual(product["productId"], f"PROD-{index:06d}")
            self.assertTrue(product["variants"][0]["sku"].startswith(f"SYN-{index:06d}-"))

    def test_overlap_and_limits_are_rejected(self):
        for target in (0, 2_000_001):
            with self.assertRaises(ValueError):
                expand(self.source, self.root, target)
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            expand(self.source, self.source / "child", 10)
        expand(self.source, self.root, 2)
        with self.assertRaisesRegex(ValueError, "preserved"):
            export(self.root, self.root / "original", metadata_only=True)

    def test_fidelity_prompt_makes_patterns_and_single_image_explicit(self):
        product, _ = fashion_product(1001, 0, 20260924, "https://test.example")
        self.assertEqual(product["pattern"], "wide stripe")
        prompt = build_fashion_prompt(product)
        self.assertIn("exactly ONE primary ecommerce photograph", prompt)
        self.assertIn("bold, broad, repeated parallel bands", prompt)
        self.assertIn("not just seams, creases, shadows", prompt)
        self.assertIn(product["colourHex"], prompt)
        self.assertIn(product["material"], prompt)
        self.assertIn(product["accent"], prompt)
        self.assertIn(product["designDetail"], prompt)
        self.assertNotIn("Trousers have", prompt)
        self.assertIn("age 25 or older", prompt)
        for pattern, instruction in PATTERN_INSTRUCTIONS.items():
            with self.subTest(pattern=pattern):
                patterned = {**product, "pattern": pattern}
                self.assertIn(instruction, build_fashion_prompt(patterned))
        with self.assertRaisesRegex(ValueError, "pattern"):
            build_fashion_prompt({**product, "pattern": "not-in-taxonomy"})
        legacy = build_fashion_prompt(product, prompt_revision=PROMPT_VERSION)
        self.assertIn(product["description"], legacy)
        self.assertNotIn("REQUIRED VISIBLE PATTERN", legacy)
        previous = build_fashion_prompt(product, prompt_revision="product-fidelity-v2")
        self.assertIn("Product accuracy has priority", previous)
        self.assertNotEqual(prompt, previous)
        self.assertIn("complete everyday outfit", prompt)
        self.assertIn("entire advertised garment", prompt)
        self.assertLess(len(prompt), len(previous))


class PipelineTests(ExpansionTests):
    def row(self, index=2):
        db = connect(self.root)
        try:
            return db.execute("SELECT * FROM products WHERE ordinal=?", (index,)).fetchone()
        finally:
            db.close()

    def prepare(self):
        expand(self.source, self.root, 3, 42)
        (self.root / "staging").mkdir()
        budget = Budget(self.root, "offline-approval", 2)
        row = self.row()
        spec = make_spec(json.loads(row["payload"]), "MAI-Image-2.6-Flash", "verified-v1", ENDPOINT)
        client = Mock()
        client.generate.side_effect = lambda _: (budget.spend(), image_bytes())[1]
        return budget, row, spec, client

    def test_successful_images_upload_and_resume_with_no_model_calls(self):
        budget, _, _, client = self.prepare()
        colours = iter((100, 101))
        client.generate.side_effect = lambda _: (budget.spend(), image_bytes(next(colours)))[1]
        publisher = Mock()
        for _ in range(2):
            result = run_batch(
                self.root, client, publisher, budget, deployment="MAI-Image-2.6-Flash",
                version="verified-v1", endpoint=ENDPOINT, start=1, end=3,
                max_products=3, workers=1,
            )
            self.assertEqual(result["states"], {"verified": 3})
        self.assertEqual(client.generate.call_count, 2)
        self.assertEqual(publisher.publish.call_count, 3)
        self.assertFalse(list((self.root / "staging").glob("*.png")))
        self.assertTrue((self.root / "original" / "images" / "prod-000001.png").exists())
        report = export(self.root, self.root / "export")
        self.assertTrue(report["ready"])

    def test_failed_upload_keeps_staging_and_does_not_regenerate(self):
        budget, row, spec, client = self.prepare()
        publisher = Mock()
        publisher.publish.side_effect = OSError("offline upload failure")
        with self.assertRaises(OSError):
            process_one(self.root, row, spec, client, publisher, budget)
        self.assertEqual(self.row()["state"], "staged")
        publisher.publish.side_effect = None
        process_one(self.root, self.row(), spec, client, publisher, budget)
        client.generate.assert_called_once()
        self.assertEqual(self.row()["state"], "verified")

    def test_uncertain_submission_is_never_automatically_retried(self):
        budget, row, spec, client = self.prepare()

        def fail(_):
            budget.spend()
            raise OSError("response lost")

        client.generate.side_effect = fail
        with self.assertRaises(OSError):
            process_one(self.root, row, spec, client, Mock(), budget)
        self.assertEqual(self.row()["state"], "uncertain")
        with self.assertRaisesRegex(ValueError, "manual reconciliation"):
            process_one(self.root, self.row(), spec, client, Mock(), budget)
        client.generate.assert_called_once()

    def test_duplicate_image_is_quarantined(self):
        budget, row, spec, client = self.prepare()
        client.generate.side_effect = lambda _: (budget.spend(), image_bytes(1))[1]
        publisher = Mock()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            process_one(self.root, row, spec, client, publisher, budget)
        self.assertEqual(self.row()["state"], "duplicate")
        publisher.publish.assert_not_called()

    def test_budget_is_durable_and_counts_attempts_not_products(self):
        budget, _, _, _ = self.prepare()
        budget.local.product_id = "PROD-000002"
        budget.spend()
        budget.spend()
        resumed = Budget(self.root, "offline-approval", 2)
        resumed.local.product_id = "PROD-000002"
        with self.assertRaises(BudgetExhausted):
            resumed.spend()
        with self.assertRaisesRegex(ValueError, "allowance changed"):
            Budget(self.root, "offline-approval", 3)

    def test_crash_after_staging_can_reconcile_without_generation(self):
        budget, _row, spec, client = self.prepare()
        encoded = json.dumps(spec, sort_keys=True)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        data = image_bytes()
        stage = self.root / "staging" / "prod-000002.png"
        stage.write_bytes(data)
        stage.with_suffix(".json").write_text(json.dumps({
            "fingerprint": fingerprint, "sha256": hashlib.sha256(data).hexdigest(),
        }))
        db = connect(self.root)
        with db:
            db.execute("UPDATE products SET state='submitted',spec=?,fingerprint=? WHERE ordinal=2",
                       (encoded, fingerprint))
        db.close()
        process_one(self.root, self.row(), spec, client, Mock(), budget)
        client.generate.assert_not_called()
        self.assertEqual(self.row()["state"], "verified")

    def test_safety_block_is_recorded_and_not_resubmitted(self):
        budget, row, spec, client = self.prepare()
        client.generate.side_effect = ContentBlocked("offline block")
        publisher = Mock()
        with self.assertRaises(ContentBlocked):
            process_one(self.root, row, spec, client, publisher, budget)
        self.assertEqual(self.row()["state"], "blocked")
        with self.assertRaisesRegex(ValueError, "not eligible"):
            process_one(self.root, self.row(), spec, client, publisher, budget)
        client.generate.assert_called_once()
        publisher.publish.assert_not_called()

    def test_zero_budget_cannot_generate(self):
        _, row, spec, client = self.prepare()
        budget = Budget(self.root, "upload-only", 0)
        client.generate.side_effect = lambda _: budget.spend()
        with self.assertRaises(BudgetExhausted):
            process_one(self.root, row, spec, client, Mock(), budget)
        self.assertEqual(self.row()["state"], "pending")

    def test_failure_before_first_http_attempt_remains_pending(self):
        budget, row, spec, client = self.prepare()
        client.generate.side_effect = RuntimeError("offline token acquisition failure")
        with self.assertRaises(RuntimeError):
            process_one(self.root, row, spec, client, Mock(), budget)
        self.assertEqual(self.row()["state"], "pending")

    def test_response_usage_is_recorded_without_image_payload(self):
        budget, _, _, _ = self.prepare()
        budget.local.product_id = "PROD-000002"
        data = image_bytes()
        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {"apim-request-id": "offline-request"}
        response.read.return_value = json.dumps({
            "data": [{"b64_json": base64.b64encode(data).decode()}],
            "usage": {"input_tokens": 100, "output_tokens": 200},
        }).encode()
        with patch("generate_images.AzureCliToken"), patch("generate_images.urlopen", return_value=response):
            client = MaiClient(ENDPOINT, 6, budget.spend, budget.record_response)
            self.assertEqual(client.generate({"width": 1024, "height": 1024}), data)
        db = connect(self.root)
        try:
            receipt = db.execute("SELECT receipt FROM responses").fetchone()[0]
            self.assertNotIn("b64_json", receipt)
            self.assertEqual(json.loads(receipt)["usage"]["output_tokens"], 200)
            self.assertEqual(db.execute("SELECT used_calls FROM budgets").fetchone()[0], 1)
        finally:
            db.close()

    def test_cleanup_after_verified_commit_does_not_generate_again(self):
        budget, row, spec, client = self.prepare()
        original_unlink = Path.unlink

        def locked(path, *args, **kwargs):
            if path.name == "prod-000002.png":
                raise PermissionError("offline transient lock")
            return original_unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", locked), self.assertRaises(PermissionError):
            process_one(self.root, row, spec, client, Mock(), budget)
        self.assertEqual(self.row()["state"], "verified")
        db = connect(self.root)
        try:
            cleanup_verified_staging(self.root, db)
        finally:
            db.close()
        self.assertFalse((self.root / "staging" / "prod-000002.png").exists())
        client.generate.assert_called_once()

    def test_blob_upload_is_conditional_and_requires_integrity(self):
        from azure.core.exceptions import ResourceNotFoundError

        self.prepare()
        path = self.root / "staging" / "offline.png"
        data = image_bytes()
        path.write_bytes(data)
        digest, md5 = validate_image(data)
        props = Mock(
            size=len(data), metadata={"sha256": digest},
            content_settings=Mock(content_md5=bytearray(md5), content_type="image/png"),
        )
        with patch("azure.identity.DefaultAzureCredential"), patch("azure.storage.blob.BlobServiceClient") as service:
            publisher = BlobPublisher("offlineaccount", "offline-images")
            blob = service.return_value.get_container_client.return_value.get_blob_client.return_value
            blob.get_blob_properties.side_effect = [ResourceNotFoundError("missing"), props]
            publisher.publish(path, path.name, digest, md5)
            self.assertFalse(blob.upload_blob.call_args.kwargs["overwrite"])
            self.assertTrue(blob.upload_blob.call_args.kwargs["validate_content"])
            props.metadata = {"sha256": "wrong"}
            blob.get_blob_properties.side_effect = None
            blob.get_blob_properties.return_value = props
            with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                publisher.publish(path, path.name, digest, md5)
            blob.upload_blob.assert_called_once()
            publisher.close()

    def test_pending_jobs_use_fidelity_revision_without_changing_recorded_spec(self):
        budget, row, spec, client = self.prepare()
        self.assertEqual(spec["promptRevision"], FIDELITY_PROMPT_VERSION)
        product = json.loads(row["payload"])
        legacy = {
            **spec, "promptRevision": PROMPT_VERSION,
            "payload": {**spec["payload"],
                        "prompt": build_fashion_prompt(product, prompt_revision=PROMPT_VERSION)},
        }
        db = connect(self.root)
        with db:
            db.execute("UPDATE products SET spec=?,fingerprint=? WHERE ordinal=2",
                       (json.dumps(legacy), hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()))
        db.close()
        run_batch(
            self.root, client, Mock(), budget, deployment="MAI-Image-2.6-Flash",
            version="verified-v1", endpoint=ENDPOINT, start=2, end=2, max_products=1, workers=1,
        )
        self.assertEqual(client.generate.call_args.args[0], legacy["payload"])
        self.assertEqual(json.loads(self.row()["spec"])["promptRevision"], PROMPT_VERSION)
        export(self.root, self.root / "metadata", metadata_only=True)
        prompts = [
            json.loads(line) for line in
            (self.root / "metadata" / "image-prompts.jsonl").read_text().splitlines()
        ]
        self.assertEqual(prompts[0]["promptRevision"], PROMPT_VERSION)
        self.assertEqual(prompts[0]["prompt"], legacy["payload"]["prompt"])
        self.assertEqual(prompts[1]["promptRevision"], FIDELITY_PROMPT_VERSION)
        self.assertEqual(len(json.loads(self.row()["payload"])["images"]), 1)

    def test_pending_only_preserves_reviewed_and_recorded_jobs_and_budget(self):
        expand(self.source, self.root, 9, 42)
        budget = Budget(self.root, "remaining-allowance", 2)
        budget.local.product_id = "PROD-000006"
        budget.spend()
        db = connect(self.root)
        with db:
            for ordinal, state in ((2, "uncertain"), (3, "blocked"), (4, "verified"),
                                   (7, "submitted"), (8, "duplicate")):
                db.execute("UPDATE products SET state=?,error='preserve evidence' WHERE ordinal=?",
                           (state, ordinal))
            db.execute("UPDATE products SET spec=? WHERE ordinal=5", ('{"recorded":"unchanged"}',))
        before = [tuple(row) for row in db.execute("SELECT * FROM products WHERE ordinal<9 ORDER BY ordinal")]
        db.close()
        client = Mock()
        client.generate.side_effect = lambda _: (budget.spend(), image_bytes())[1]
        publisher = Mock()
        for _ in range(2):
            result = run_batch(
                self.root, client, publisher, budget, deployment="MAI-Image-2.6-Flash",
                version="verified-v1", endpoint=ENDPOINT, start=1, end=9,
                max_products=9, workers=2, pending_only=True,
            )
            self.assertFalse(result["ready"])
            self.assertEqual(result["unresolvedReviewCount"], 3)
            self.assertEqual(result["submittedHttpRequests"], 2)
            self.assertEqual(result["maximumHttpRequests"], 2)
            self.assertEqual(result["selectionMode"], "unsubmitted-only")
        client.generate.assert_called_once()
        publisher.publish.assert_called_once()
        self.assertEqual(publisher.publish.call_args.args[1], "prod-000009.png")
        self.assertEqual(json.loads(self.row(9)["spec"])["promptRevision"], FIDELITY_PROMPT_VERSION)
        db = connect(self.root)
        try:
            after = [tuple(row) for row in db.execute("SELECT * FROM products WHERE ordinal<9 ORDER BY ordinal")]
            self.assertEqual(before, after)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

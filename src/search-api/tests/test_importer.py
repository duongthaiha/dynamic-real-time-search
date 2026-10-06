from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from azure.cosmos.exceptions import CosmosResourceNotFoundError
from test_search import document, settings

from catalog_search.cosmos import FULL_TEXT_POLICY, IMPORT_MARKER, INDEXING_POLICY
from catalog_search.importer import fingerprint, import_documents


class ImportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stored = {}
        self.container = MagicMock()
        self.container.read = AsyncMock(
            return_value={
                "partitionKey": {"paths": ["/scopeId"]},
                "indexingPolicy": INDEXING_POLICY,
                "fullTextPolicy": FULL_TEXT_POLICY,
            }
        )

        async def read_item(item, **kwargs):
            if item not in self.stored:
                raise CosmosResourceNotFoundError(status_code=404, message="not found")
            return self.stored[item]

        async def create_item(item):
            self.stored[item["id"]] = item.copy()
            return item

        async def upsert_item(item):
            self.stored[item["id"]] = item.copy()
            return item

        self.container.read_item = AsyncMock(side_effect=read_item)
        self.container.create_item = AsyncMock(side_effect=create_item)
        self.container.upsert_item = AsyncMock(side_effect=upsert_item)

        async def counts():
            yield len(self.stored) - (IMPORT_MARKER in self.stored)

        self.container.query_items.side_effect = lambda *a, **k: counts()

        @asynccontextmanager
        async def connect(_):
            yield self.container

        self.connection = patch("catalog_search.importer.connect", connect)
        self.connection.start()
        self.addCleanup(self.connection.stop)

    async def test_import_verify_ready_and_idempotent_rerun(self):
        item = document()
        summary = await import_documents([item], settings().database)
        self.assertEqual(summary["status"], "ready")
        self.assertEqual(summary["productCount"], 1)
        self.assertEqual(summary["variantCount"], 7)
        self.assertEqual(summary["contentSha256"], fingerprint([item]))
        self.assertEqual(self.container.create_item.await_count, 2)
        self.assertEqual(self.container.upsert_item.await_count, 1)
        await import_documents([item], settings().database)
        self.assertEqual(self.container.create_item.await_count, 2)
        self.assertEqual(self.container.upsert_item.await_count, 1)

    async def test_different_epoch_or_content_rejected(self):
        item = document()
        await import_documents([item], settings().database)
        changed = item.model_copy(update={"title": "changed"})
        with self.assertRaisesRegex(ValueError, "different import"):
            await import_documents([changed], settings().database)

    async def test_partial_import_resumes(self):
        item = document()
        self.stored[IMPORT_MARKER] = {
            "status": "importing",
            "importEpoch": settings().database.import_epoch,
            "contentSha256": fingerprint([item]),
        }
        await import_documents([item], settings().database)
        self.assertEqual(self.stored[IMPORT_MARKER]["status"], "ready")

    async def test_corrupted_ready_import_is_not_repaired(self):
        item = document()
        await import_documents([item], settings().database)
        del self.stored[item.id]
        with self.assertRaisesRegex(ValueError, "missing a product"):
            await import_documents([item], settings().database)

    async def test_changed_document_is_not_overwritten(self):
        item = document()
        await import_documents([item], settings().database)
        self.stored[item.id]["title"] = "changed"
        with self.assertRaisesRegex(ValueError, "differs from import"):
            await import_documents([item], settings().database)

    async def test_extra_product_prevents_publication(self):
        self.stored["unrelated"] = {"id": "unrelated"}
        with self.assertRaisesRegex(ValueError, "not empty"):
            await import_documents([document()], settings().database)
        self.assertNotIn(IMPORT_MARKER, self.stored)

    async def test_partial_failure_never_publishes_ready(self):
        self.container.create_item.side_effect = [
            {"id": IMPORT_MARKER},
            RuntimeError("write interrupted"),
        ]
        with self.assertRaises(RuntimeError):
            await import_documents([document()], settings().database)
        self.container.upsert_item.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

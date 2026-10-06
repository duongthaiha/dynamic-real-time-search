from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch as mock_patch

from azure.cosmos.exceptions import CosmosHttpResponseError
from fastapi.testclient import TestClient
from jsonschema import Draft4Validator, FormatChecker
from openapi_spec_validator import validate
from pydantic import ValidationError

from catalog_search.app import create_app, public_product
from catalog_search.catalog import CatalogDocument, load_catalog, map_product, minor_units
from catalog_search.config import ClientGrant, DatabaseSettings, Settings
from catalog_search.cosmos import CosmosRepository, SearchResult, validate_container
from catalog_search.evaluate import percentile, quality
from catalog_search.models import SearchRequest, ServiceError
from catalog_search.query import build_query, eligible_variants

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = json.loads((ROOT / "docs" / "api" / "search.openapi.json").read_text(encoding="utf-8"))
KEY = "offline-test-credential"
SCOPE = "demo-store"
EPOCH = "test-001"


def settings(**overrides) -> Settings:
    return Settings(
        database=DatabaseSettings(
            endpoint="https://example.documents.azure.com",
            database="offline",
            container="offline",
            import_epoch=EPOCH,
        ),
        clients=[
            ClientGrant(
                key_sha256=hashlib.sha256(KEY.encode()).hexdigest(),
                scope_id=SCOPE,
                areas=["storefront"],
                collections=["products"],
            )
        ],
        **overrides,
    )


def source() -> dict:
    with (ROOT / "data" / "catalog" / "products.jsonl").open(encoding="utf-8") as stream:
        return json.loads(next(stream), parse_float=Decimal)


def document() -> CatalogDocument:
    return map_product(source(), SCOPE, "storefront", EPOCH)


def request(**overrides) -> SearchRequest:
    return SearchRequest.model_validate(
        {"area": "storefront", "collection": "products", "query": "green jeans", **overrides}
    )


def headers() -> dict[str, str]:
    return {"Authorization": f"client-key {KEY}", "x-customer-id": SCOPE}


def schema(name: str) -> Draft4Validator:
    return Draft4Validator(
        {"$ref": f"#/components/schemas/{name}", "components": CONTRACT["components"]},
        format_checker=FormatChecker(),
    )


class FakeRepository:
    def __init__(self):
        self.last_request: SearchRequest | None = None
        self.error: Exception | None = None
        self.total = 1
        self.items = [document()]
        self.ready_calls = 0

    async def ready(self, scope: str) -> None:
        self.ready_calls += 1

    async def search(self, body: SearchRequest, scope: str) -> SearchResult:
        self.last_request = body
        if self.error:
            raise self.error
        return SearchResult(self.items, self.total, 3.5, build_query(body, scope, EPOCH))


class ContractTests(unittest.TestCase):
    def test_openapi_and_examples(self):
        validate(CONTRACT)
        operation = CONTRACT["paths"]["/v1/search"]["post"]
        for example in operation["requestBody"]["content"]["application/json"]["examples"].values():
            schema("SearchRequest").validate(example["value"])
            SearchRequest.model_validate(example["value"])
        schema("SearchResponse").validate(
            operation["responses"]["200"]["content"]["application/json"]["example"]
        )

    def test_strict_models_and_nulls(self):
        for patch in (
            {"skip": True},
            {"skip": "0"},
            {"pageSize": 0},
            {"debug": "true"},
            {"query": " "},
            {"refinements": None},
            {"sessionId": None},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                request(**patch)
        self.assertEqual(request(unknownCompatibilityOption={"anything": True}).pageSize, 20)

    def test_numeric_range_validation(self):
        for low, high in ((2, 1), ("1", 2), (True, 2), (float("inf"), 2)):
            with self.subTest(low=low), self.assertRaises(ValidationError):
                request(
                    refinements=[
                        {"navigationName": "price", "type": "Range", "low": low, "high": high}
                    ]
                )


class CatalogTests(unittest.TestCase):
    def test_relative_images_have_no_storage_account_in_cosmos(self):
        item = map_product(source(), SCOPE, "storefront", "images-001", "product-images")
        payload = item.model_dump(exclude_none=True)
        self.assertEqual(item.schemaVersion, "cosmos-catalog-v2")
        self.assertEqual(payload["imagePath"], "product-images/prod-000001.png")
        self.assertNotIn("imageUrl", payload)
        self.assertNotIn("url", payload["images"][0])
        self.assertEqual(payload["images"][0]["path"], payload["imagePath"])
        first = public_product(
            item, request(), SCOPE, "images-001", None, "https://devimages.blob.core.windows.net"
        )
        second = public_product(
            item, request(), SCOPE, "images-001", None, "https://prodimages.blob.core.windows.net"
        )
        self.assertEqual(
            first.imageUrl, "https://devimages.blob.core.windows.net/product-images/prod-000001.png"
        )
        self.assertEqual(
            second.imageUrl,
            "https://prodimages.blob.core.windows.net/product-images/prod-000001.png",
        )
        self.assertEqual(item.model_dump(exclude_none=True), payload)
        schema("Product").validate(first.model_dump())

    def test_relative_images_require_explicit_origin(self):
        item = map_product(source(), SCOPE, "storefront", EPOCH, "product-images")
        with self.assertRaises(ServiceError) as caught:
            public_product(item, request(), SCOPE, EPOCH, None)
        self.assertEqual(caught.exception.code, "IMAGE_CONFIGURATION")

    def test_relative_image_paths_reject_unsafe_inputs(self):
        item = map_product(source(), SCOPE, "storefront", EPOCH, "product-images")
        for value in (
            "../secret.png",
            "https://evil.example/a.png",
            "/images/a.png",
            "product-images/../secret.png",
            "product-images/a.png?token=secret",
        ):
            payload = item.model_dump(exclude_none=True)
            payload["imagePath"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CatalogDocument.model_validate(payload)
        for value in ("../images", "Images", "a", "bad--name"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                map_product(source(), SCOPE, "storefront", EPOCH, value)

    def test_image_origin_rejects_credentials_paths_and_query_tokens(self):
        for value in (
            "http://account.example",
            "https://user:secret@account.example",
            "https://account.example/container",
            "https://account.example?token=secret",
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                settings().database.model_validate(
                    {**settings().database.model_dump(), "image_base_url": value}
                )

    def test_whole_catalog_mapping_and_no_source_changes(self):
        path = ROOT / "data" / "catalog" / "products.jsonl"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        docs = load_catalog(path, SCOPE, "storefront", EPOCH)
        self.assertEqual(len(docs), 1000)
        self.assertEqual(sum(len(doc.variants) for doc in docs), 6136)
        self.assertEqual(len({doc.id for doc in docs}), 1000)
        self.assertEqual(docs[0].priceMinor, 2850)
        self.assertEqual(docs[0].attributes["color"], "green")
        self.assertIn("utility detailing", docs[0].searchText)
        self.assertEqual(docs[0].imageUrl, source()["imageUrl"])
        self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_invalid_catalog(self):
        for patch in (
            {"currency": "USD"},
            {"price": float("inf")},
            {"price": True},
            {"createdAt": "2026-01-01T00:00:00"},
            {"isInStock": False},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                map_product({**source(), **patch}, SCOPE, "storefront", EPOCH)

    def test_duplicate_catalog_products_rejected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.jsonl"
            item = json.dumps(source(), default=float)
            path.write_text(item + "\n" + item, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "line 2"):
                load_catalog(path, SCOPE, "storefront", EPOCH)

    def test_money(self):
        self.assertEqual(minor_units(Decimal("28.50")), 2850)
        for value in (-1, True, "28.50", Decimal("0.001"), Decimal("1e999999")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                minor_units(value)


class QueryTests(unittest.TestCase):
    def test_full_text_matching_and_count_share_predicate(self):
        plan = build_query(request(), SCOPE, EPOCH)
        self.assertIn("FullTextContainsAll(c.searchText", plan.count_sql)
        self.assertIn("ORDER BY RANK FullTextScore", plan.records_sql)
        self.assertEqual(
            plan.count_sql.split(" WHERE ")[1],
            plan.records_sql.split(" WHERE ")[1].split(" ORDER BY RANK")[0],
        )
        self.assertNotIn("FullTextScore", plan.count_sql)
        self.assertNotIn("OFFSET", plan.records_sql)

    def test_unsafe_values_are_parameters(self):
        body = request(
            query="jeans ' OR true --",
            refinements=[{"navigationName": "brand", "type": "Value", "value": "x') OR true --"}],
        )
        plan = build_query(body, SCOPE, EPOCH)
        self.assertNotIn("x') OR true", plan.records_sql)
        self.assertIn("x') or true --", [parameter["value"] for parameter in plan.parameters])

    def test_injection_field_rejected(self):
        with self.assertRaises(ServiceError) as caught:
            build_query(
                request(
                    refinements=[
                        {"navigationName": "c.brand) OR true", "type": "Value", "value": "anything"}
                    ]
                ),
                SCOPE,
                EPOCH,
            )
        self.assertEqual(caught.exception.status, 422)

    def test_refinement_grouping(self):
        plan = build_query(
            request(
                refinements=[
                    {"navigationName": "attributes.color", "type": "Value", "value": "green"},
                    {"navigationName": "attributes.color", "type": "Value", "value": "blue"},
                    {"navigationName": "brand", "type": "Value", "value": "Alder Studio"},
                ]
            ),
            SCOPE,
            EPOCH,
        )
        self.assertIn(" OR ", plan.count_sql)
        self.assertIn("LOWER(c.brand)", plan.count_sql)
        with self.assertRaises(ServiceError) as caught:
            build_query(
                request(
                    refinements=[
                        {
                            "navigationName": "category",
                            "type": "Value",
                            "value": "jeans",
                            "or": True,
                        },
                        {
                            "navigationName": "category",
                            "type": "Value",
                            "value": "jackets",
                            "or": False,
                        },
                    ]
                ),
                SCOPE,
                EPOCH,
            )
        self.assertEqual(caught.exception.status, 400)

    def test_same_variant_stock_size_and_price(self):
        item = document()
        item.variants[0].priceMinor = 4000
        for variant in item.variants[1:]:
            variant.size = "different"
        body = request(
            refinements=[
                {"navigationName": "attributes.size", "type": "Value", "value": "W28 L30"},
                {"navigationName": "price", "type": "Range", "low": 20, "high": 30},
            ]
        )
        self.assertEqual(eligible_variants(item, body, None), [])
        plan = build_query(body, SCOPE, EPOCH)
        self.assertEqual(plan.count_sql.count("EXISTS("), 1)
        self.assertIn("v.size", plan.variant_predicate)
        self.assertIn("v.priceMinor", plan.variant_predicate)
        self.assertIn("v.isInStock", plan.variant_predicate)

    def test_and_on_size_cannot_match_different_variants(self):
        body = request(
            refinements=[
                {
                    "navigationName": "attributes.size",
                    "type": "Value",
                    "value": "W28 L30",
                    "or": False,
                },
                {
                    "navigationName": "attributes.size",
                    "type": "Value",
                    "value": "W30 L30",
                    "or": False,
                },
            ]
        )
        self.assertEqual(eligible_variants(document(), body, None), [])

    def test_inclusive_decimal_range(self):
        body = request(
            refinements=[
                {
                    "navigationName": "price",
                    "type": "Range",
                    "low": Decimal("28.5"),
                    "high": Decimal("28.5"),
                }
            ]
        )
        self.assertEqual(len(eligible_variants(document(), body, None)), 6)
        plan = build_query(body, SCOPE, EPOCH)
        self.assertIn(2850, [item["value"] for item in plan.parameters])
        fractional = request(
            refinements=[
                {
                    "navigationName": "price",
                    "type": "Range",
                    "low": Decimal("28.501"),
                    "high": Decimal("28.509"),
                }
            ]
        )
        self.assertEqual(eligible_variants(document(), fractional, None), [])

    def test_identifiers(self):
        for query, identifier in (
            ("prod-000001", "PROD-000001"),
            ("syn-000001-01", "SYN-000001-01"),
        ):
            plan = build_query(request(query=query), SCOPE, EPOCH)
            self.assertEqual(plan.identifier, identifier)
            self.assertNotIn("FullText", plan.records_sql)
        body = request(query="SYN-000001-07")
        self.assertEqual(eligible_variants(document(), body, "SYN-000001-07"), [])

    def test_unsupported_and_limits(self):
        for patch in (
            {"enableTopsort": True},
            {"sponsoredRecords": {}},
            {"pageSize": 101},
            {"skip": 1000},
            {"query": "!"},
            {"query": "x" * 513},
        ):
            with self.subTest(patch=patch), self.assertRaises(ServiceError):
                build_query(request(**patch), SCOPE, EPOCH)
        build_query(request(skip=900, pageSize=100), SCOPE, EPOCH)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.client = TestClient(
            create_app(settings(), self.repository), raise_server_exceptions=False
        )
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def post(self, patch=None, request_headers=None):
        return self.client.post(
            "/v1/search",
            headers=headers() if request_headers is None else request_headers,
            json={
                "area": "storefront",
                "collection": "products",
                "query": "green jeans",
                **(patch or {}),
            },
        )

    def assert_error(self, response, status):
        self.assertEqual(response.status_code, status, response.text)
        schema("Error").validate(response.json())
        self.assertEqual(response.json()["requestId"], response.headers["X-Request-Id"])

    def test_success_shape(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        schema("SearchResponse").validate(response.json())
        self.assertEqual(response.json()["id"], response.headers["X-Request-Id"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json()["records"][0]["price"], 28.5)
        self.assertNotIn("searchAttributionToken", response.json())
        self.assertFalse(response.json()["degraded"])
        self.assertEqual(response.json()["pageSize"], 20)
        assert self.repository.last_request is not None
        self.assertEqual(self.repository.last_request.query, "green jeans")

    def test_authentication_and_scope(self):
        for credential in ("Bearer secret", "client-key bad", "client-key ", ""):
            self.assert_error(
                self.post(request_headers={**headers(), "Authorization": credential}), 401
            )
        self.assert_error(
            self.post(request_headers={**headers(), "x-customer-id": "another-store"}), 403
        )
        self.assert_error(self.post(request_headers={"Authorization": f"client-key {KEY}"}), 400)
        self.assert_error(self.post({"area": "admin"}), 403)
        self.assert_error(self.post({"collection": "other"}), 403)

    def test_validation_errors_use_contract(self):
        for patch in (
            {"query": ""},
            {"skip": -1},
            {"pageSize": 0},
            {"skip": "0"},
            {"debug": 1},
            {"query": " "},
            {"refinements": None},
        ):
            self.assert_error(self.post(patch), 400)
        for body in (
            '{"query":',
            '{"area":"storefront","collection":"products","query":"jeans","price":NaN}',
        ):
            result = self.client.post(
                "/v1/search",
                headers={**headers(), "Content-Type": "application/json"},
                content=body,
            )
            self.assert_error(result, 400)

    def test_unsupported_options_and_diagnostics(self):
        self.assert_error(self.post({"enableTopsort": True}), 422)
        self.assert_error(self.post({"sponsoredRecords": {}}), 422)
        self.assert_error(self.post({"pageSize": 101}), 422)
        self.assert_error(self.post({"debug": True}), 403)
        self.assert_error(
            self.post(request_headers={**headers(), "x-groupby-skip-cache": "true"}), 403
        )
        self.assert_error(
            self.post(request_headers={**headers(), "x-groupby-skip-cache": "not-bool"}), 400
        )
        self.assertEqual(self.post({"enableTopsort": False, "unknown": 1}).status_code, 200)

    def test_authorized_debug_without_data_leak(self):
        config = settings()
        config.clients[0].diagnostics = True
        with TestClient(create_app(config, self.repository)) as client:
            result = client.post(
                "/v1/search",
                headers={**headers(), "x-groupby-skip-cache": "true"},
                json={
                    "area": "storefront",
                    "collection": "products",
                    "query": "jeans",
                    "debug": True,
                },
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["X-Cosmos-Request-Units"], "3.500")
        self.assertNotIn("searchText", result.text)

    def test_dependency_failure_and_unexpected_error(self):
        self.repository.error = ServiceError(
            503, "COSMOS_UNAVAILABLE", "Catalogue dependency is unavailable."
        )
        self.assert_error(self.post(), 503)
        self.repository.error = RuntimeError("secret payload")
        with self.assertLogs("catalog_search", level="ERROR") as captured:
            self.assert_error(self.post(), 500)
        self.assertNotIn("secret payload", " ".join(captured.output))

    def test_real_total_not_page_length(self):
        self.repository.total = 123
        response = self.post()
        self.assertEqual(response.json()["totalRecords"], 123)
        self.assertEqual(len(response.json()["records"]), 1)
        self.repository.items = []
        result = self.post({"skip": 500})
        self.assertEqual(result.json()["skip"], 500)
        self.assertEqual(result.json()["records"], [])
        self.assertEqual(result.json()["totalRecords"], 123)

    def test_body_limit_and_rate_limit(self):
        with TestClient(create_app(settings(max_body_bytes=100), self.repository)) as client:
            result = client.post("/v1/search", headers=headers(), json={"query": "x" * 101})
            self.assert_error(result, 422)
        with TestClient(create_app(settings(requests_per_minute=1), self.repository)) as client:
            payload = {"area": "storefront", "collection": "products", "query": "jeans"}
            self.assertEqual(
                client.post("/v1/search", headers=headers(), json=payload).status_code, 200
            )
            result = client.post("/v1/search", headers=headers(), json=payload)
            self.assert_error(result, 429)
            self.assertGreaterEqual(int(result.headers["Retry-After"]), 1)

    def test_corrupted_scope_fails(self):
        self.repository.items[0].scopeId = "another-store"
        self.assert_error(self.post(), 503)

    def test_health(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        self.assertGreaterEqual(self.repository.ready_calls, 2)

    def test_success_telemetry_does_not_log_shopper_context(self):
        with self.assertLogs("catalog_search", level="INFO") as captured:
            response = self.post({"sessionId": "private-session", "visitorId": "private-visitor"})
        self.assertEqual(response.status_code, 200)
        logs = " ".join(captured.output)
        self.assertIn("search_complete", logs)
        self.assertIn("ru=3.50", logs)
        for value in (KEY, "private-session", "private-visitor", "green jeans"):
            self.assertNotIn(value, logs)

    def test_startup_dependency_failure_is_explicit_and_sanitized(self):
        class UnreadyRepository(FakeRepository):
            async def ready(self, scope: str) -> None:
                raise CosmosHttpResponseError(status_code=403, message="sensitive SDK detail")

        with self.assertRaisesRegex(RuntimeError, "COSMOS_STARTUP_FAILURE") as caught:
            with TestClient(create_app(settings(), UnreadyRepository())):
                self.fail("Startup must not succeed.")
        self.assertNotIn("sensitive", str(caught.exception))


class RepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_relative_snapshot_readiness_requires_image_origin(self):
        from catalog_search.cosmos import FULL_TEXT_POLICY, INDEXING_POLICY

        container = MagicMock()
        container.read = AsyncMock(
            return_value={
                "partitionKey": {"paths": ["/scopeId"]},
                "indexingPolicy": INDEXING_POLICY,
                "fullTextPolicy": FULL_TEXT_POLICY,
            }
        )
        container.read_item = AsyncMock(
            return_value={
                "status": "ready",
                "importEpoch": EPOCH,
                "schemaVersion": "cosmos-import-v1",
                "catalogSchemaVersion": "cosmos-catalog-v2",
            }
        )
        with self.assertRaises(ServiceError) as caught:
            await CosmosRepository(container, settings().database).ready(SCOPE)
        self.assertEqual(caught.exception.code, "IMAGE_CONFIGURATION")
        container.query_items.assert_not_called()

    async def test_failed_sdk_initialization_closes_transport(self):
        from catalog_search.cosmos import connect

        client = MagicMock()
        client.__aenter__ = AsyncMock(
            side_effect=CosmosHttpResponseError(status_code=403, message="denied")
        )
        client.close = AsyncMock()
        credential = MagicMock()
        credential.__aenter__ = AsyncMock(return_value=credential)
        credential.__aexit__ = AsyncMock(return_value=False)
        with (
            mock_patch("catalog_search.cosmos.CosmosClient", return_value=client),
            mock_patch("catalog_search.cosmos.DefaultAzureCredential", return_value=credential),
        ):
            with self.assertRaises(CosmosHttpResponseError):
                async with connect(settings().database):
                    self.fail("SDK initialization must fail.")
        client.close.assert_awaited_once()
        credential.__aexit__.assert_awaited_once()

    async def test_adapter_queries_and_charges(self):
        container = MagicMock()
        calls = []

        def query(sql, **kwargs):
            calls.append((sql, kwargs))

            async def rows():
                kwargs["response_hook"]({"x-ms-request-charge": "2.5"}, {})
                if sql.startswith("SELECT VALUE COUNT"):
                    yield 1
                else:
                    yield document().model_dump()

            return rows()

        container.query_items.side_effect = query
        repository = CosmosRepository(container, settings().database)
        result = await repository.search(request(), SCOPE)
        self.assertEqual(result.total, 1)
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(result.request_units, 5)
        self.assertEqual(calls[0][1]["parameters"], calls[1][1]["parameters"])
        self.assertEqual(calls[0][1]["partition_key"], SCOPE)

    async def test_adapter_throttle_is_error(self):
        container = MagicMock()

        def query(*args, **kwargs):
            async def rows():
                raise CosmosHttpResponseError(status_code=429, message="sensitive diagnostic")
                yield

            return rows()

        container.query_items.side_effect = query
        with self.assertRaises(ServiceError) as caught:
            await CosmosRepository(container, settings().database).search(request(), SCOPE)
        self.assertEqual(caught.exception.code, "COSMOS_THROTTLED")
        self.assertNotIn("sensitive", caught.exception.message)

    async def test_adapter_rejects_count_shape(self):
        container = MagicMock()

        async def rows():
            yield -1

        container.query_items.side_effect = lambda *a, **k: rows()
        with self.assertRaises(ServiceError):
            await CosmosRepository(container, settings().database).search(request(), SCOPE)

    async def test_adapter_consumes_ranked_prefix_and_slices_offset(self):
        container = MagicMock()
        docs = [
            document().model_copy(update={"id": f"PROD-{i:06}", "productId": f"PROD-{i:06}"})
            for i in range(1, 4)
        ]

        def query(sql, **kwargs):
            async def rows():
                if sql.startswith("SELECT VALUE COUNT"):
                    yield 10
                else:
                    for item in docs:
                        yield item.model_dump()

            return rows()

        container.query_items.side_effect = query
        result = await CosmosRepository(container, settings().database).search(
            request(skip=2, pageSize=1), SCOPE
        )
        self.assertEqual(result.total, 10)
        self.assertEqual([item.id for item in result.documents], ["PROD-000003"])
        self.assertIn("SELECT TOP", result.plan.records_sql)
        self.assertIn("* FROM c", result.plan.records_sql)

    async def test_adapter_inconsistent_prefix_is_error(self):
        container = MagicMock()

        def query(sql, **kwargs):
            async def rows():
                if sql.startswith("SELECT VALUE COUNT"):
                    yield 20
                else:
                    yield document().model_dump()

            return rows()

        container.query_items.side_effect = query
        with self.assertRaises(ServiceError) as caught:
            await CosmosRepository(container, settings().database).search(request(), SCOPE)
        self.assertEqual(caught.exception.code, "CATALOG_CHANGED")

    async def test_adapter_deadline(self):
        container = MagicMock()

        async def rows():
            await asyncio.sleep(1)
            yield 1

        container.query_items.side_effect = lambda *a, **k: rows()
        config = settings().database.model_copy(update={"deadline_seconds": 0.01})
        with self.assertRaises(ServiceError) as caught:
            await CosmosRepository(container, config).search(request(), SCOPE)
        self.assertEqual(caught.exception.code, "COSMOS_DEADLINE")

    def test_container_policy(self):
        from catalog_search.cosmos import FULL_TEXT_POLICY, INDEXING_POLICY

        properties = {
            "partitionKey": {"paths": ["/scopeId"]},
            "indexingPolicy": INDEXING_POLICY,
            "fullTextPolicy": FULL_TEXT_POLICY,
        }
        validate_container(properties)
        broken = deepcopy(properties)
        broken["indexingPolicy"]["fullTextIndexes"] = []
        with self.assertRaises(ServiceError):
            validate_container(broken)


class EvaluationTests(unittest.TestCase):
    def test_metrics_and_partial_judgments(self):
        self.assertEqual(
            quality(["a", "b"], {"a": 3, "b": 1}, True), {"ndcgAt10": 1.0, "recallAt20": 1.0}
        )
        self.assertIsNone(quality(["a"], {"a": 3}, False)["recallAt20"])
        self.assertIsNone(quality([], {}, True)["ndcgAt10"])
        self.assertEqual(percentile([1, 2, 3, 4], 0.95), 4)


if __name__ == "__main__":
    unittest.main()

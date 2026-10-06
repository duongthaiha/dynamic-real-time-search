import unittest

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from test_search import KEY, FakeRepository, schema, settings

from catalog_search.app import create_app


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.config = settings(demo_enabled=True, demo_client_key=SecretStr(KEY))
        self.client = TestClient(
            create_app(self.config, self.repository),
            base_url="http://127.0.0.1",
            client=("127.0.0.1", 50000),
        )
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_demo_is_disabled_by_default(self):
        with TestClient(create_app(settings(), self.repository)) as client:
            self.assertEqual(client.get("/demo").status_code, 404)

    def test_static_page_and_assets_do_not_contain_credentials(self):
        for path in ("/demo", "/demo/assets/demo.css", "/demo/assets/demo.js"):
            reply = self.client.get(path)
            self.assertEqual(reply.status_code, 200)
            self.assertNotIn(KEY, reply.text)
            self.assertIn("frame-ancestors 'none'", reply.headers["Content-Security-Policy"])
            self.assertEqual(reply.headers["Cache-Control"], "no-store")
        self.assertNotIn("demo_client_key", self.config.model_dump())
        self.assertEqual(self.client.get("/demo/assets/config.py").status_code, 404)

    def test_proxy_uses_real_api_contract_and_server_credential(self):
        reply = self.client.post(
            "/demo/search", json={"query": "green jeans", "skip": 0, "pageSize": 20}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        schema("SearchResponse").validate(reply.json())
        self.assertEqual(reply.json()["id"], reply.headers["X-Request-Id"])
        self.assertNotIn(KEY, reply.text)
        assert self.repository.last_request is not None
        self.assertEqual(self.repository.last_request.area, "storefront")
        self.assertEqual(self.repository.last_request.collection, "products")
        self.assertFalse(self.repository.last_request.debug)

    def test_scope_and_diagnostic_overrides_are_rejected(self):
        for key in ("area", "collection", "debug", "enableTopsort"):
            reply = self.client.post("/demo/search", json={"query": "jeans", key: "override"})
            self.assertEqual(reply.status_code, 400)
            schema("Error").validate(reply.json())

    def test_errors_are_not_replaced_with_empty_results(self):
        for patch, status in (({"query": ""}, 400), ({"query": "jeans", "pageSize": 101}, 422)):
            reply = self.client.post("/demo/search", json=patch)
            self.assertEqual(reply.status_code, status)
            schema("Error").validate(reply.json())
        reply = self.client.post(
            "/demo/search", content='{"query":NaN}', headers={"Content-Type": "application/json"}
        )
        self.assertEqual(reply.status_code, 400)

    def test_cross_origin_and_non_loopback_access_are_denied(self):
        reply = self.client.post(
            "/demo/search", json={"query": "jeans"}, headers={"Origin": "https://evil.example"}
        )
        self.assertEqual(reply.status_code, 403)
        reply = self.client.get("/demo", headers={"Host": "evil.example"})
        self.assertEqual(reply.status_code, 403)
        with TestClient(
            create_app(self.config, self.repository),
            base_url="http://127.0.0.1",
            client=("192.0.2.1", 50000),
        ) as remote:
            self.assertEqual(remote.get("/demo").status_code, 403)
        reply = self.client.post(
            "/demo/search", json={"query": "jeans"}, headers={"Origin": "http://127.0.0.1"}
        )
        self.assertEqual(reply.status_code, 200)

    def test_unconfigured_or_wrong_demo_key_fails_configuration(self):
        for key in (None, SecretStr("not-authorized")):
            with self.assertRaises(ValidationError):
                settings(demo_enabled=True, demo_client_key=key)


if __name__ == "__main__":
    unittest.main()

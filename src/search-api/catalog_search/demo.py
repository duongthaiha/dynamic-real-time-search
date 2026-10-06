from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from .config import Settings
from .models import ServiceError, reject_json_constant

WEB = Path(__file__).parent / "web"
PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src https: data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def register_demo(app: FastAPI, settings: Settings) -> None:
    if not settings.demo_enabled:
        return
    if settings.demo_client_key is None:
        raise ValueError("Enabled demo requires a server-side client key.")
    key = settings.demo_client_key.get_secret_value()
    digest = hashlib.sha256(key.encode()).hexdigest()
    grant = next(grant for grant in settings.clients if grant.key_sha256 == digest)

    def local_only(request: Request) -> None:
        if (
            request.client is None
            or request.client.host not in ("127.0.0.1", "::1")
            or request.url.hostname not in ("127.0.0.1", "localhost", "::1")
        ):
            raise ServiceError(403, "DEMO_LOCAL_ONLY", "The demo is available only on loopback.")
        origin = request.headers.get("origin")
        if origin is not None and origin != f"{request.url.scheme}://{request.headers.get('host')}":
            raise ServiceError(403, "DEMO_ORIGIN", "Cross-origin demo requests are not authorized.")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise ServiceError(403, "DEMO_ORIGIN", "Cross-site demo requests are not authorized.")

    @app.get("/demo", include_in_schema=False)
    async def page(request: Request):
        local_only(request)
        return FileResponse(WEB / "index.html", headers=PAGE_HEADERS)

    @app.get("/demo/assets/{name}", include_in_schema=False)
    async def asset(request: Request, name: str):
        local_only(request)
        if name not in ("demo.css", "demo.js"):
            raise ServiceError(404, "NOT_FOUND", "Demo asset not found.")
        return FileResponse(WEB / name, headers=PAGE_HEADERS)

    @app.post("/demo/search", include_in_schema=False)
    async def proxy(request: Request):
        local_only(request)
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise ServiceError(400, "INVALID_REQUEST", "Demo requests require application/json.")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > settings.max_body_bytes:
                raise ServiceError(422, "BODY_LIMIT", "Request body limit exceeded.")
            body.extend(chunk)
        try:
            payload = json.loads(body, parse_constant=reject_json_constant)
        except (ValueError, UnicodeError) as error:
            raise ServiceError(400, "INVALID_REQUEST", "Malformed demo request.") from error
        if not isinstance(payload, dict) or set(payload) - {
            "query",
            "skip",
            "pageSize",
            "refinements",
        }:
            raise ServiceError(400, "INVALID_REQUEST", "Unsupported demo request fields.")
        payload["area"] = settings.demo_area
        payload["collection"] = settings.demo_collection
        transport = httpx.ASGITransport(
            app=app, raise_app_exceptions=False, client=("127.0.0.1", 0)
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            reply = await client.post(
                "/v1/search",
                headers={"Authorization": f"client-key {key}", "x-customer-id": grant.scope_id},
                json=payload,
            )
        request.state.request_id = reply.headers["X-Request-Id"]
        headers = {
            name: value
            for name, value in reply.headers.items()
            if name.lower() in ("content-type", "cache-control", "x-request-id", "retry-after")
        }
        return Response(reply.content, status_code=reply.status_code, headers=headers)

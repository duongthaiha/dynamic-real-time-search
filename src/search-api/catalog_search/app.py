from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import time
from collections import deque
from contextlib import AsyncExitStack, asynccontextmanager
from decimal import Decimal
from uuid import uuid4

from azure.core.exceptions import AzureError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .catalog import CatalogDocument
from .config import ClientGrant, Settings
from .cosmos import CosmosRepository, SearchRepository, connect
from .demo import register_demo
from .models import Product, SearchRequest, SearchResponse, ServiceError, reject_json_constant
from .query import eligible_variants, validate_options

LOGGER = logging.getLogger("catalog_search")


def authenticate(request: Request, settings: Settings) -> ClientGrant:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, key = authorization.partition(" ")
    if scheme != "client-key" or not separator or not key or any(c.isspace() for c in key):
        raise ServiceError(401, "UNAUTHORIZED", "A valid client-key credential is required.")
    digest = hashlib.sha256(key.encode()).hexdigest()
    matches = [grant for grant in settings.clients if hmac.compare_digest(grant.key_sha256, digest)]
    if not matches:
        raise ServiceError(401, "UNAUTHORIZED", "A valid client-key credential is required.")
    return matches[0]


def public_product(
    document: CatalogDocument,
    body: SearchRequest,
    scope: str,
    epoch: str,
    identifier: str | None,
    image_base_url: str | None = None,
) -> Product:
    if (
        document.scopeId != scope
        or document.area != body.area
        or document.collection != body.collection
        or document.importEpoch != epoch
        or not document.isSearchable
    ):
        raise ServiceError(
            503, "CATALOG_INVALID", "Catalogue result scope or eligibility is invalid."
        )
    variants = eligible_variants(document, body, identifier)
    if not variants:
        raise ServiceError(503, "CATALOG_INVALID", "Catalogue returned an ineligible product.")
    if document.imagePath is not None:
        if image_base_url is None:
            raise ServiceError(
                503,
                "IMAGE_CONFIGURATION",
                "Relative catalogue images require CATALOG_IMAGE_BASE_URL.",
            )
        image_url = f"{image_base_url.rstrip('/')}/{document.imagePath}"
    elif document.imageUrl is not None:
        image_url = document.imageUrl
    else:
        raise ServiceError(503, "CATALOG_INVALID", "Catalogue image reference is missing.")
    return Product(
        productId=document.productId,
        title=document.title,
        price=min(variant.priceMinor for variant in variants) / 100,
        currency=document.currency,
        category=document.category,
        collection=document.collection,
        imageUrl=image_url,
        attributes=document.attributes,
    )


def create_app(
    settings: Settings | None = None, repository: SearchRepository | None = None
) -> FastAPI:
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
    configured = settings or Settings.from_env()
    active_repository = repository
    semaphore = asyncio.Semaphore(configured.max_concurrent)
    arrivals = {grant.key_sha256: deque[float]() for grant in configured.clients}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        nonlocal active_repository
        async with AsyncExitStack() as stack:
            try:
                if active_repository is None:
                    container = await stack.enter_async_context(connect(configured.database))
                    active_repository = CosmosRepository(container, configured.database)
                for scope in {grant.scope_id for grant in configured.clients}:
                    await active_repository.ready(scope)
            except (AzureError, TimeoutError, ServiceError) as error:
                code = error.code if isinstance(error, ServiceError) else "COSMOS_STARTUP_FAILURE"
                LOGGER.error("startup_failed code=%s type=%s", code, type(error).__name__)
                raise RuntimeError(
                    f"Catalogue startup failed: {code}. Verify configuration and authorized access."
                ) from None
            yield

    app = FastAPI(
        title="Search Service API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    async def error_response(request: Request, error: ServiceError) -> JSONResponse:
        LOGGER.warning(
            "request_failed request_id=%s status=%s code=%s",
            request.state.request_id,
            error.status,
            error.code,
        )
        headers = {"X-Request-Id": request.state.request_id, "Cache-Control": "no-store"}
        if error.retry_after is not None:
            headers["Retry-After"] = str(error.retry_after)
        return JSONResponse(
            status_code=error.status,
            content={
                "code": error.code,
                "message": error.message,
                "requestId": request.state.request_id,
            },
            headers=headers,
        )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        return await error_response(request, error)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _: RequestValidationError):
        return await error_response(
            request, ServiceError(400, "INVALID_REQUEST", "Invalid request.")
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return await error_response(
            request, ServiceError(error.status_code, "HTTP_ERROR", "Request could not be served.")
        )

    @app.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception):
        # Log the type only: exception messages can contain payloads or SDK credentials.
        LOGGER.error(
            "unexpected_error request_id=%s type=%s", request.state.request_id, type(error).__name__
        )
        return await error_response(
            request, ServiceError(500, "INTERNAL_ERROR", "Unexpected server failure.")
        )

    @app.get("/health/live")
    async def live():
        return {"status": "live"}

    @app.get("/health/ready")
    async def ready():
        if active_repository is None:
            raise ServiceError(503, "CATALOG_NOT_READY", "Catalogue is not ready.")
        for scope in {grant.scope_id for grant in configured.clients}:
            await active_repository.ready(scope)
        return {"status": "ready"}

    @app.post("/v1/search")
    async def search(request: Request):
        grant = authenticate(request, configured)
        scope = request.headers.get("x-customer-id")
        if scope is None or not scope.strip():
            raise ServiceError(400, "INVALID_REQUEST", "x-customer-id is required.")
        if scope != grant.scope_id:
            raise ServiceError(403, "FORBIDDEN", "Customer scope is not authorized.")
        if (
            request.headers.get("content-type", "").split(";")[0].strip().lower()
            != "application/json"
        ):
            raise ServiceError(400, "INVALID_REQUEST", "Content-Type must be application/json.")
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > configured.max_body_bytes:
                raise ServiceError(422, "BODY_LIMIT", "Request body limit exceeded.")
            data.extend(chunk)
        try:
            payload = json.loads(data, parse_float=Decimal, parse_constant=reject_json_constant)
            body = SearchRequest.model_validate(payload)
        except (ValueError, UnicodeError) as error:
            raise ServiceError(
                400, "INVALID_REQUEST", "Malformed JSON or invalid request fields."
            ) from error
        if body.area not in grant.areas or body.collection not in grant.collections:
            raise ServiceError(403, "FORBIDDEN", "Area or collection is not authorized.")
        bypass = request.headers.get("x-groupby-skip-cache")
        if bypass is not None and bypass.lower() not in ("true", "false"):
            raise ServiceError(400, "INVALID_REQUEST", "Cache bypass header must be true or false.")
        if (
            body.debug or bypass is not None and bypass.lower() == "true"
        ) and not grant.diagnostics:
            raise ServiceError(403, "FORBIDDEN", "Diagnostic options require authorization.")
        validate_options(
            body, configured.max_query_chars, configured.max_terms, configured.max_refinements
        )
        now = time.monotonic()
        window = arrivals[grant.key_sha256]
        while window and now - window[0] >= 60:
            window.popleft()
        if len(window) >= configured.requests_per_minute:
            raise ServiceError(
                429, "RATE_LIMIT", "Request rate exceeded.", math.ceil(60 - (now - window[0]))
            )
        if semaphore.locked():
            raise ServiceError(429, "CONCURRENCY_LIMIT", "Search concurrency limit exceeded.", 1)
        window.append(now)
        if active_repository is None:
            raise ServiceError(503, "CATALOG_NOT_READY", "Catalogue is not ready.")
        started = time.perf_counter()
        try:
            async with semaphore, asyncio.timeout(configured.database.deadline_seconds):
                result = await active_repository.search(body, scope)
                records = [
                    public_product(
                        document,
                        body,
                        scope,
                        configured.database.import_epoch,
                        result.plan.identifier,
                        configured.database.image_base_url,
                    )
                    for document in result.documents
                ]
        except TimeoutError as error:
            raise ServiceError(
                503, "COSMOS_DEADLINE", "Catalogue dependency deadline exceeded."
            ) from error
        except ValidationError as error:
            raise ServiceError(
                503, "CATALOG_INVALID", "Catalogue result validation failed."
            ) from error
        response = SearchResponse(
            id=request.state.request_id,
            query=body.query,
            skip=body.skip,
            pageSize=body.pageSize,
            totalRecords=result.total,
            records=records,
        )
        LOGGER.info(
            "search_complete request_id=%s mode=keyword epoch=%s elapsed_ms=%.2f ru=%.2f records=%s",
            request.state.request_id,
            configured.database.import_epoch,
            (time.perf_counter() - started) * 1000,
            result.request_units,
            len(records),
        )
        headers = {"X-Cosmos-Request-Units": f"{result.request_units:.3f}"} if body.debug else None
        return JSONResponse(response.model_dump(), headers=headers)

    register_demo(app, configured)
    return app

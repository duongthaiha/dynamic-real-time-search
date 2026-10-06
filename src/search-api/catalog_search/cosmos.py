from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from azure.core.exceptions import AzureError
from azure.cosmos.aio import ContainerProxy, CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.identity.aio import DefaultAzureCredential
from pydantic import ValidationError

from .catalog import CatalogDocument
from .config import DatabaseSettings
from .models import SearchRequest, ServiceError
from .query import QueryPlan, build_query

IMPORT_MARKER = "__catalog_import__"
FULL_TEXT_POLICY = {
    "defaultLanguage": "en-US",
    "fullTextPaths": [{"path": "/searchText", "language": "en-US"}],
}
INDEXING_POLICY = {
    "indexingMode": "consistent",
    "automatic": True,
    "includedPaths": [{"path": "/*"}],
    "excludedPaths": [{"path": '/"_etag"/?'}],
    "fullTextIndexes": [{"path": "/searchText"}],
}


@dataclass(frozen=True)
class SearchResult:
    documents: list[CatalogDocument]
    total: int
    request_units: float
    plan: QueryPlan


class SearchRepository(Protocol):
    async def ready(self, scope: str, /) -> None: ...
    async def search(self, request: SearchRequest, scope: str, /) -> SearchResult: ...


def dependency_error(error: AzureError) -> ServiceError:
    status = error.status_code if isinstance(error, CosmosHttpResponseError) else None
    code = "COSMOS_THROTTLED" if status == 429 else "COSMOS_UNAVAILABLE"
    return ServiceError(503, code, "Catalogue dependency is unavailable.")


@asynccontextmanager
async def connect(settings: DatabaseSettings):
    async with AsyncExitStack() as stack:
        async with asyncio.timeout(settings.deadline_seconds):
            credential = await stack.enter_async_context(DefaultAzureCredential())
            client = CosmosClient(
                settings.endpoint,
                credential=credential,
                consistency_level="Session",
                connection_timeout=settings.deadline_seconds,
                read_timeout=settings.deadline_seconds,
                retry_total=3,
                retry_throttle_total=3,
                retry_backoff_max=settings.deadline_seconds,
                retry_throttle_backoff_max=settings.deadline_seconds,
                logging_enable=False,
            )
            # SDK initialization can fail before __aenter__ registers its own cleanup.
            stack.push_async_callback(client.close)
            await client.__aenter__()
        yield client.get_database_client(settings.database).get_container_client(settings.container)


def validate_container(properties: Mapping[str, object]) -> None:
    partition = properties.get("partitionKey")
    policy = properties.get("indexingPolicy")
    text = properties.get("fullTextPolicy")
    if not isinstance(partition, dict) or partition.get("paths") != ["/scopeId"]:
        raise ServiceError(
            503, "CATALOG_CONFIGURATION", "Container must use /scopeId partitioning."
        )
    if (
        not isinstance(policy, dict)
        or policy.get("indexingMode") != "consistent"
        or policy.get("automatic") is not True
        or {"path": "/*"} not in policy.get("includedPaths", [])
        or {"path": "/searchText"} not in policy.get("fullTextIndexes", [])
        or not isinstance(text, dict)
        or {"path": "/searchText", "language": "en-US"} not in text.get("fullTextPaths", [])
    ):
        raise ServiceError(
            503, "CATALOG_CONFIGURATION", "Required English full-text index is missing."
        )


class CosmosRepository:
    def __init__(self, container: ContainerProxy, settings: DatabaseSettings):
        self.container = container
        self.settings = settings

    async def ready(self, scope: str) -> None:
        try:
            async with asyncio.timeout(self.settings.deadline_seconds):
                validate_container(await self.container.read())
                marker = await self.container.read_item(IMPORT_MARKER, partition_key=scope)
                if (
                    marker.get("status") != "ready"
                    or marker.get("importEpoch") != self.settings.import_epoch
                    or marker.get("schemaVersion") != "cosmos-import-v1"
                ):
                    raise ServiceError(
                        503, "CATALOG_NOT_READY", "A verified catalogue import is required."
                    )
                if (
                    marker.get("catalogSchemaVersion") == "cosmos-catalog-v2"
                    and self.settings.image_base_url is None
                ):
                    raise ServiceError(
                        503,
                        "IMAGE_CONFIGURATION",
                        "Relative catalogue images require CATALOG_IMAGE_BASE_URL.",
                    )
                # Exercise the indexed path, not just account/container connectivity.
                probe = SearchRequest(
                    area="storefront", collection="products", query="jeans", pageSize=1
                )
                await self.search(probe, scope)
        except TimeoutError as error:
            raise ServiceError(
                503, "COSMOS_DEADLINE", "Catalogue dependency deadline exceeded."
            ) from error
        except AzureError as error:
            raise dependency_error(error) from error

    async def search(self, request: SearchRequest, scope: str) -> SearchResult:
        plan = build_query(request, scope, self.settings.import_epoch)
        charge = 0.0

        def response_hook(headers: Mapping[str, str], _: object) -> None:
            nonlocal charge
            charge += float(headers.get("x-ms-request-charge", "0"))

        try:
            async with asyncio.timeout(self.settings.deadline_seconds):
                counts = [
                    item
                    async for item in self.container.query_items(
                        plan.count_sql,
                        parameters=plan.parameters,
                        partition_key=scope,
                        response_hook=response_hook,
                        enable_scan_in_query=False,
                    )
                ]
                if len(counts) != 1 or type(counts[0]) is not int or counts[0] < 0:
                    raise ServiceError(
                        503, "CATALOG_INVALID", "Catalogue returned an invalid total."
                    )
                total = counts[0]
                documents = []
                if request.skip < total:
                    async for item in self.container.query_items(
                        plan.records_sql,
                        parameters=plan.parameters,
                        partition_key=scope,
                        max_item_count=100,
                        response_hook=response_hook,
                        enable_scan_in_query=False,
                    ):
                        documents.append(CatalogDocument.model_validate(item))
                        if len(documents) > request.skip + request.pageSize:
                            raise ServiceError(
                                503, "CATALOG_INVALID", "Catalogue exceeded the query limit."
                            )
                if len(documents) != (
                    min(total, request.skip + request.pageSize) if request.skip < total else 0
                ):
                    raise ServiceError(
                        503, "CATALOG_CHANGED", "Catalogue count and results are inconsistent."
                    )
                if len({document.id for document in documents}) != len(documents):
                    raise ServiceError(
                        503, "CATALOG_INVALID", "Catalogue returned duplicate products."
                    )
                return SearchResult(documents[request.skip :], total, charge, plan)
        except TimeoutError as error:
            raise ServiceError(
                503, "COSMOS_DEADLINE", "Catalogue dependency deadline exceeded."
            ) from error
        except AzureError as error:
            raise dependency_error(error) from error
        except ValidationError as error:
            raise ServiceError(
                503, "CATALOG_INVALID", "Catalogue document validation failed."
            ) from error

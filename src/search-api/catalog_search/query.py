from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR

from .catalog import CatalogDocument, Variant, normalize
from .models import Refinement, SearchRequest, ServiceError, ValueRefinement

VALUE_FIELDS = {
    "attributes.color": "c.attributes.color",
    "category": "c.category",
    "brand": "c.brand",
    "department": "c.department",
    "productType": "c.productType",
    "attributes.fit": "c.attributes.fit",
    "attributes.material": "c.attributes.material",
    "attributes.size": "v.size",
}


@dataclass(frozen=True)
class QueryPlan:
    count_sql: str
    records_sql: str
    parameters: list[dict[str, object]]
    variant_predicate: str
    identifier: str | None


def validate_options(
    request: SearchRequest, max_query: int, max_terms: int, max_refinements: int
) -> list[str]:
    if request.enableTopsort or request.sponsoredRecords is not None:
        raise ServiceError(422, "UNSUPPORTED_OPTION", "Sponsorship and Topsort are not supported.")
    if request.pageSize > 100 or request.skip + request.pageSize > 1000:
        raise ServiceError(
            422, "PAGINATION_LIMIT", "pageSize <= 100 and skip + pageSize <= 1000 required."
        )
    terms = re.findall(r"\w+(?:[-']\w+)*", normalize(request.query), flags=re.UNICODE)
    if not terms:
        raise ServiceError(400, "INVALID_QUERY", "Query must contain a searchable term.")
    if (
        len(request.query) > max_query
        or len(terms) > max_terms
        or len(request.refinements) > max_refinements
    ):
        raise ServiceError(422, "REQUEST_LIMIT", "Query or refinement limit exceeded.")
    groups: dict[str, list[Refinement]] = {}
    for refinement in request.refinements:
        if isinstance(refinement, ValueRefinement):
            if refinement.navigationName not in VALUE_FIELDS:
                raise ServiceError(
                    422, "UNSUPPORTED_REFINEMENT", "Unsupported value refinement field."
                )
            if not normalize(refinement.value):
                raise ServiceError(400, "INVALID_REFINEMENT", "Refinement value must not be blank.")
        else:
            if refinement.navigationName != "price":
                raise ServiceError(
                    422, "UNSUPPORTED_REFINEMENT", "Only price supports range refinements."
                )
            if abs(refinement.low) > 10**12 or abs(refinement.high) > 10**12:
                raise ServiceError(
                    422, "REQUEST_LIMIT", "Price range magnitude must not exceed 1e12."
                )
        groups.setdefault(refinement.navigationName, []).append(refinement)
    if any(len({r.or_ for r in group}) > 1 for group in groups.values()):
        raise ServiceError(
            400, "REFINEMENT_MODE", "Mixed AND/OR modes for one field are not supported."
        )
    return terms


def build_query(request: SearchRequest, scope: str, epoch: str) -> QueryPlan:
    terms = validate_options(request, 512, 32, 32)
    parameters: list[dict[str, object]] = []

    def parameter(value: object) -> str:
        name = f"@p{len(parameters)}"
        parameters.append({"name": name, "value": value})
        return name

    parent = [
        f"c.scopeId = {parameter(scope)}",
        f"c.area = {parameter(request.area)}",
        f"c.collection = {parameter(request.collection)}",
        f"c.importEpoch = {parameter(epoch)}",
        "c.schemaVersion IN ('cosmos-catalog-v1', 'cosmos-catalog-v2')",
        "c.currency = 'GBP'",
        "c.isSearchable = true",
        "c.isInStock = true",
    ]
    variant = ["v.isInStock = true", "v.stockQuantity > 0", "v.currency = 'GBP'"]
    identifier = request.query.strip().upper()
    is_product = re.fullmatch(r"PROD-\d{6}", identifier) is not None
    is_sku = re.fullmatch(r"SYN-\d{6}-\d{2}", identifier) is not None
    if is_product:
        parent.append(f"c.productId = {parameter(identifier)}")
    elif is_sku:
        variant.append(f"v.sku = {parameter(identifier)}")
    else:
        identifier = None
    groups: dict[str, list[Refinement]] = {}
    for refinement in request.refinements:
        groups.setdefault(refinement.navigationName, []).append(refinement)
    for name, group in groups.items():
        predicates = []
        for refinement in group:
            if isinstance(refinement, ValueRefinement):
                predicates.append(
                    f"LOWER({VALUE_FIELDS[name]}) = {parameter(normalize(refinement.value))}"
                )
            else:
                low = int((refinement.low * 100).to_integral_value(rounding=ROUND_CEILING))
                high = int((refinement.high * 100).to_integral_value(rounding=ROUND_FLOOR))
                predicates.append(
                    f"(v.priceMinor >= {parameter(low)} AND v.priceMinor <= {parameter(high)})"
                )
        grouped = "(" + (" OR " if group[0].or_ else " AND ").join(predicates) + ")"
        (variant if name in ("price", "attributes.size") else parent).append(grouped)
    variant_predicate = " AND ".join(variant)
    parent.append(f"EXISTS(SELECT VALUE v FROM v IN c.variants WHERE {variant_predicate})")
    order = ""
    if identifier is None:
        term_args = ", ".join(parameter(term) for term in terms)
        parent.append(f"FullTextContainsAll(c.searchText, {term_args})")
        order = f" ORDER BY RANK FullTextScore(c.searchText, {term_args})"
    where = " AND ".join(parent)
    prefix = parameter(request.skip + request.pageSize)
    return QueryPlan(
        count_sql=f"SELECT VALUE COUNT(1) FROM c WHERE {where}",
        records_sql=f"SELECT TOP {prefix} * FROM c WHERE {where}{order}",
        parameters=parameters,
        variant_predicate=variant_predicate,
        identifier=identifier,
    )


def eligible_variants(
    document: CatalogDocument, request: SearchRequest, identifier: str | None
) -> list[Variant]:
    matches = []
    for variant in document.variants:
        if not variant.isInStock or variant.stockQuantity <= 0:
            continue
        if identifier and identifier.startswith("SYN-") and variant.sku != identifier:
            continue
        groups: dict[str, list[Refinement]] = {}
        for refinement in request.refinements:
            if refinement.navigationName in ("price", "attributes.size"):
                groups.setdefault(refinement.navigationName, []).append(refinement)
        valid = True
        for group in groups.values():
            outcomes = [
                normalize(variant.size) == normalize(refinement.value)
                if isinstance(refinement, ValueRefinement)
                else refinement.low * 100 <= variant.priceMinor <= refinement.high * 100
                for refinement in group
            ]
            valid = valid and (any(outcomes) if group[0].or_ else all(outcomes))
        if valid:
            matches.append(variant)
    return matches

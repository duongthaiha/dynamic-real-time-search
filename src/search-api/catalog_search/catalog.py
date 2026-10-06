from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def minor_units(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Price must be numeric.")
    price = Decimal(str(value))
    if not price.is_finite() or price < 0 or price > Decimal("1000000000000"):
        raise ValueError("Price must be finite and between zero and 1e12.")
    scaled = price * 100
    if scaled != scaled.to_integral_value():
        raise ValueError("Price must be finite, nonnegative and have at most two decimal places.")
    return int(scaled)


class Variant(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    variantId: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    size: str = Field(min_length=1)
    color: str = Field(min_length=1)
    priceMinor: int = Field(ge=0)
    currency: str = Field(pattern="^GBP$")
    stockQuantity: int = Field(ge=0)
    isInStock: bool

    @model_validator(mode="after")
    def stock_consistent(self) -> Variant:
        if self.isInStock != (self.stockQuantity > 0):
            raise ValueError("Stock flag and quantity must agree.")
        return self


def validate_image_path(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError("Image path must be a relative container/blob path without traversal.")
    return value


class CatalogDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")
    id: str = Field(min_length=1)
    schemaVersion: Literal["cosmos-catalog-v1", "cosmos-catalog-v2"]
    scopeId: str = Field(min_length=1)
    area: str = Field(min_length=1)
    collection: str = Field(min_length=1)
    catalogVersion: str = Field(min_length=1)
    importEpoch: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    productId: str = Field(min_length=1)
    colourWayId: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str
    brand: str = Field(min_length=1)
    department: str = Field(min_length=1)
    category: str = Field(min_length=1)
    productType: str = Field(min_length=1)
    attributes: dict[str, str]
    tags: list[str]
    searchText: str = Field(min_length=1)
    priceMinor: int = Field(ge=0)
    currency: str = Field(pattern="^GBP$")
    isSearchable: bool
    isInStock: bool
    imageUrl: str | None = None
    imagePath: str | None = None
    images: list[dict[str, object]]
    variants: list[Variant] = Field(min_length=1)
    sourceCreatedAt: str
    sourceUpdatedAt: str

    @field_validator("imageUrl")
    @classmethod
    def image_uri(cls, value: str | None) -> str | None:
        if value is not None and not re.match(r"^https?://[^/\s]+", value):
            raise ValueError("Image URL must be an HTTP(S) URI.")
        return value

    @field_validator("imagePath")
    @classmethod
    def relative_image(cls, value: str | None) -> str | None:
        return validate_image_path(value) if value is not None else None

    @field_validator("sourceCreatedAt", "sourceUpdatedAt")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("Source timestamps must be UTC.")
        return value

    @model_validator(mode="after")
    def coherent(self) -> CatalogDocument:
        if self.schemaVersion == "cosmos-catalog-v1":
            if self.imageUrl is None or self.imagePath is not None:
                raise ValueError("Legacy catalogue requires only an absolute imageUrl.")
        else:
            if self.imagePath is None or self.imageUrl is not None:
                raise ValueError("Catalogue v2 requires only a relative imagePath.")
            for image in self.images:
                path = image.get("path")
                if not isinstance(path, str) or "url" in image:
                    raise ValueError(
                        "Catalogue v2 gallery entries require relative paths, not URLs."
                    )
                validate_image_path(path)
        if self.id != self.productId:
            raise ValueError("Cosmos id must equal productId.")
        if self.isInStock != any(variant.isInStock for variant in self.variants):
            raise ValueError("Parent stock must agree with variants.")
        if len({variant.sku for variant in self.variants}) != len(self.variants):
            raise ValueError("Duplicate SKU within product.")
        if len({variant.variantId for variant in self.variants}) != len(self.variants):
            raise ValueError("Duplicate variant ID within product.")
        return self


def map_product(
    source: dict[str, object],
    scope: str,
    area: str,
    epoch: str,
    image_container: str | None = None,
) -> CatalogDocument:
    raw_variants = source["variants"]
    if not isinstance(raw_variants, list):
        raise ValueError("Variants must be an array.")
    variants = []
    for raw in raw_variants:
        if not isinstance(raw, dict):
            raise ValueError("Variant must be an object.")
        variants.append(
            Variant.model_validate(
                {
                    "variantId": raw["variantId"],
                    "sku": raw["sku"],
                    "size": raw["size"],
                    "color": normalize(str(source["colour"])),
                    "priceMinor": minor_units(raw["price"]),
                    "currency": raw["currency"],
                    "stockQuantity": raw["stockQuantity"],
                    "isInStock": raw["isInStock"],
                }
            )
        )
    attributes = {
        "color": source["colour"],
        "colorName": source["colourName"],
        "colorHex": source["colourHex"],
        "fit": source["fit"],
        "material": source["material"],
    }
    searchable = [
        source[key]
        for key in (
            "title",
            "brand",
            "department",
            "category",
            "productType",
            "colour",
            "fit",
            "material",
            "description",
        )
    ]
    tags = source["tags"]
    if not all(isinstance(value, str) for value in searchable):
        raise ValueError("Search attributes must be strings.")
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("Tags must be strings.")
    image_fields: dict[str, object] = {"imageUrl": source["imageUrl"], "images": source["images"]}
    if image_container is not None:
        if not 3 <= len(image_container) <= 63 or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", image_container
        ):
            raise ValueError("Image container must be a valid Azure blob container name.")
        local_path = source["imagePath"]
        gallery = source["images"]
        if not isinstance(local_path, str) or not isinstance(gallery, list):
            raise ValueError("Image source paths/gallery are invalid.")
        filename = local_path.replace("\\", "/").rsplit("/", 1)[-1]
        images = []
        for item in gallery:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise ValueError("Gallery source URL is invalid.")
            name = urlsplit(item["url"]).path.rsplit("/", 1)[-1]
            images.append(
                {
                    **{key: value for key, value in item.items() if key != "url"},
                    "path": validate_image_path(f"{image_container}/{name}"),
                }
            )
        image_fields = {
            "imagePath": validate_image_path(f"{image_container}/{filename}"),
            "images": images,
        }
    return CatalogDocument.model_validate(
        {
            "id": source["productId"],
            "schemaVersion": "cosmos-catalog-v2" if image_container else "cosmos-catalog-v1",
            "scopeId": scope,
            "area": area,
            "collection": source["collection"],
            "catalogVersion": source["catalogVersion"],
            "importEpoch": epoch,
            "productId": source["productId"],
            "colourWayId": source["colourWayId"],
            "title": source["title"],
            "description": source["description"],
            "brand": source["brand"],
            "department": source["department"],
            "category": source["category"],
            "productType": source["productType"],
            "attributes": attributes,
            "tags": tags,
            "searchText": normalize(" ".join(str(value) for value in [*searchable, *tags])),
            "priceMinor": minor_units(source["price"]),
            "currency": source["currency"],
            "isSearchable": source["isSearchable"],
            "isInStock": source["isInStock"],
            **image_fields,
            "variants": variants,
            "sourceCreatedAt": source["createdAt"],
            "sourceUpdatedAt": source["updatedAt"],
        }
    )


def load_catalog(
    path: Path,
    scope: str,
    area: str,
    epoch: str,
    image_container: str | None = None,
) -> list[CatalogDocument]:
    documents = []
    product_ids: set[str] = set()
    skus: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line_number > 1000 or len(line) > 262144:
                raise ValueError("POC import is limited to 1000 products of at most 256 KiB each.")
            try:
                source = json.loads(line, parse_float=Decimal)
                if not isinstance(source, dict):
                    raise ValueError("Product must be an object.")
                document = map_product(source, scope, area, epoch, image_container)
                if document.id in product_ids or any(v.sku in skus for v in document.variants):
                    raise ValueError("Duplicate product or SKU.")
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f"Invalid catalogue record at line {line_number}.") from error
            documents.append(document)
            product_ids.add(document.id)
            skus.update(v.sku for v in document.variants)
    if not documents:
        raise ValueError("Catalogue is empty.")
    return documents

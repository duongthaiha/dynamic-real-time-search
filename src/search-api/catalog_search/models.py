from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1)]


def reject_json_constant(_: str) -> None:
    raise ValueError("Non-finite JSON number.")


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def no_explicit_nulls(cls, value: object) -> object:
        if isinstance(value, dict):
            names = {field.alias or name for name, field in cls.model_fields.items()}
            if any(name in names and item is None for name, item in value.items()):
                raise ValueError("Known fields do not accept null.")
        return value


class RefinementBase(WireModel):
    navigationName: Text
    or_: bool = Field(default=True, alias="or")
    count: int | None = Field(default=None, ge=0)
    pinned: bool | None = None


class ValueRefinement(RefinementBase):
    type: Literal["Value"]
    value: Text


class RangeRefinement(RefinementBase):
    type: Literal["Range"]
    low: Decimal
    high: Decimal

    @field_validator("low", "high", mode="before")
    @classmethod
    def numeric_endpoint(cls, value: object) -> Decimal:
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            raise ValueError("Range endpoints must be numbers.")
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Range endpoints must be finite.")
        return number

    @model_validator(mode="after")
    def ordered(self) -> RangeRefinement:
        if self.low > self.high:
            raise ValueError("Range low must not exceed high.")
        return self


Refinement = Annotated[ValueRefinement | RangeRefinement, Field(discriminator="type")]


class SponsoredRecords(WireModel):
    positions: list[Annotated[int, Field(ge=0)]] | None = None
    count: int | None = Field(default=None, ge=0)


class SearchRequest(WireModel):
    area: Text
    collection: Text
    query: Text
    skip: int = Field(default=0, ge=0)
    pageSize: int = Field(default=20, ge=1)
    refinements: list[Refinement] = Field(default_factory=list)
    debug: bool = False
    enableTopsort: bool = False
    sessionId: Text | None = None
    visitorId: Text | None = None
    sponsoredRecords: SponsoredRecords | None = None

    @field_validator("area", "collection", "query")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be whitespace.")
        return value


class Product(WireModel):
    productId: Text
    title: Text
    price: float = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    category: str
    collection: str
    imageUrl: str
    attributes: dict[str, str]


class SearchResponse(WireModel):
    id: Text
    query: str
    skip: int = Field(ge=0)
    pageSize: int = Field(ge=1)
    totalRecords: int = Field(ge=0)
    records: list[Product]
    degraded: bool = False


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.retry_after = retry_after

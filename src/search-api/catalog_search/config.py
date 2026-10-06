from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class ClientGrant(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope_id: str = Field(min_length=1)
    areas: list[str] = Field(min_length=1)
    collections: list[str] = Field(min_length=1)
    diagnostics: bool = False


class DatabaseSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    endpoint: str
    database: str = Field(min_length=1)
    container: str = Field(min_length=1)
    import_epoch: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    deadline_seconds: float = Field(default=10.0, gt=0, le=60)
    image_base_url: str | None = None

    @field_validator("image_base_url")
    @classmethod
    def image_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "Image base must be an HTTPS storage/CDN origin without path or credentials."
            )
        return value.rstrip("/")

    @field_validator("endpoint")
    @classmethod
    def https_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Cosmos endpoint must be HTTPS without embedded credentials.")
        return value

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        return cls(
            endpoint=os.environ["COSMOS_ENDPOINT"],
            database=os.environ["COSMOS_DATABASE"],
            container=os.environ["COSMOS_CONTAINER"],
            import_epoch=os.environ["CATALOG_IMPORT_EPOCH"],
            image_base_url=os.environ.get("CATALOG_IMAGE_BASE_URL"),
        )


class Settings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    database: DatabaseSettings
    clients: list[ClientGrant] = Field(min_length=1)
    max_body_bytes: int = Field(default=65536, gt=0, le=1048576)
    max_query_chars: int = Field(default=512, gt=0, le=4096)
    max_terms: int = Field(default=32, gt=0, le=100)
    max_refinements: int = Field(default=32, gt=0, le=100)
    max_concurrent: int = Field(default=16, gt=0, le=100)
    requests_per_minute: int = Field(default=120, gt=0)
    demo_enabled: bool = False
    demo_client_key: SecretStr | None = Field(default=None, exclude=True)
    demo_area: str = "storefront"
    demo_collection: str = "products"

    @model_validator(mode="after")
    def demo_credential_scope(self) -> Settings:
        if self.demo_enabled:
            if self.demo_client_key is None:
                raise ValueError("Enabled demo requires a server-side client key file.")
            key = self.demo_client_key.get_secret_value()
            if not key or any(character.isspace() for character in key):
                raise ValueError("Demo client key is invalid.")
            digest = hashlib.sha256(key.encode()).hexdigest()
            grants = [grant for grant in self.clients if grant.key_sha256 == digest]
            if (
                len(grants) != 1
                or self.demo_area not in grants[0].areas
                or self.demo_collection not in grants[0].collections
            ):
                raise ValueError(
                    "Demo credential is not authorized for the configured area/collection."
                )
        return self

    @field_validator("clients")
    @classmethod
    def unique_keys(cls, value: list[ClientGrant]) -> list[ClientGrant]:
        if len({grant.key_sha256 for grant in value}) != len(value):
            raise ValueError("Each client credential must have exactly one grant.")
        return value

    @classmethod
    def from_env(cls) -> Settings:
        path = Path(os.environ["SEARCH_CLIENTS_FILE"])
        demo_flag = os.environ.get("SEARCH_DEMO_ENABLED", "false").lower()
        if demo_flag not in ("true", "false"):
            raise ValueError("SEARCH_DEMO_ENABLED must be true or false.")
        demo_enabled = demo_flag == "true"
        demo_key = (
            SecretStr(Path(os.environ["SEARCH_DEMO_CLIENT_KEY_FILE"]).read_text().strip())
            if demo_enabled
            else None
        )
        return cls(
            database=DatabaseSettings.from_env(),
            clients=[ClientGrant.model_validate(item) for item in json.loads(path.read_text())],
            demo_enabled=demo_enabled,
            demo_client_key=demo_key,
        )

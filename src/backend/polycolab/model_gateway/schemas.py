"""HTTP schemas owned by the model_gateway capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from polycolab.app.schemas import ApiModel, RequestModel


class ProviderConnectionCreate(RequestModel):
    display_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=2048)
    model_id: str = Field(min_length=1, max_length=500)
    api_key: SecretStr = Field(min_length=1, max_length=20_000)
    wire_api: Literal["responses", "chat_completions"] = "responses"


class ProviderConnectionRotate(RequestModel):
    api_key: SecretStr = Field(min_length=1, max_length=20_000)


class ProviderConnectionRead(ApiModel):
    api_key_preview: str | None = None
    id: UUID
    display_name: str
    base_url: str
    model_id: str
    wire_api: Literal["responses", "chat_completions"]
    encryption_key_version: str
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ProviderConnectionCreate",
    "ProviderConnectionRotate",
    "ProviderConnectionRead",
]


class PlatformModelRead(ApiModel):
    id: UUID
    catalog_id: str
    display_name: str
    model_id: str
    uses: list[str]
    harnesses: list[str]
    default_for: list[str]

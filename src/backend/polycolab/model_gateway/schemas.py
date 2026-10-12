"""HTTP schemas owned by the model_gateway capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr

from polycolab.app.schemas import ApiModel, RequestModel


class GatewayProfileCreate(RequestModel):
    display_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=2048)
    model_id: str = Field(min_length=1, max_length=500)
    api_key: SecretStr = Field(min_length=1, max_length=20_000)
    wire_api: Literal["responses", "chat_completions"] = "responses"


class GatewayProfileRotate(RequestModel):
    api_key: SecretStr = Field(min_length=1, max_length=20_000)


class GatewayProfileRead(ApiModel):
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
    "GatewayProfileCreate",
    "GatewayProfileRotate",
    "GatewayProfileRead",
]

"""HTTP schemas owned by the agents capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_serializer

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import (
    AgentRunEventKind,
    PlatformAgentKind,
)


class PlatformAgentRead(ApiModel):
    id: UUID
    agent_kind: PlatformAgentKind
    version: int
    display_name: str


class AgentRunEventRead(ApiModel):
    run_id: UUID
    cursor: int
    kind: AgentRunEventKind
    payload: dict[str, object]
    occurred_at: datetime


class ExternalCredentialCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)


class ExternalCredentialRead(ApiModel):
    secret_reveal_available: bool = False
    id: UUID
    project_id: UUID | None
    scope_kind: Literal["ACCOUNT", "PROJECT"]
    sponsor_user_id: UUID
    name: str
    fixed_rights: list[str]

    @field_serializer("fixed_rights")
    def current_rights(self, value: list[str]) -> list[str]:
        from polycolab.platform.project_history import credential_right

        return [credential_right(right) for right in value]

    expires_at: datetime
    revoked_at: datetime | None
    request_count: int
    mutation_count: int
    max_requests: int
    max_mutations: int
    created_at: datetime


class ExternalCredentialIssued(ExternalCredentialRead):
    # List projections never contain this field.
    secret: str


class ContextManifestRead(ApiModel):
    id: UUID
    run_id: UUID
    project_id: UUID
    artifact_ids: list[UUID]
    digest: str
    created_at: datetime

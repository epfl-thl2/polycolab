"""HTTP schemas owned by the agents capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, model_validator

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    AgentSessionStatus,
    PlatformAgentKind,
)


class PlatformAgentRead(ApiModel):
    id: UUID
    agent_kind: PlatformAgentKind
    version: int
    display_name: str


class AgentSessionCreate(RequestModel):
    worktree_id: UUID | None = None
    task_id: UUID | None = None
    project_id: UUID
    agent_kind: PlatformAgentKind
    title: str | None = Field(default=None, max_length=300)
    agent_version: Literal[1, 2, 3] = 3
    harness: Literal["codex"] | None = None
    system_prompt: str | None = Field(default=None, min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def custom_configuration(self) -> AgentSessionCreate:
        if self.task_id and self.worktree_id and self.task_id != self.worktree_id:
            raise ValueError("task_id and worktree_id must agree")
        self.task_id = self.worktree_id or self.task_id
        if (self.harness is None) != (self.system_prompt is None):
            raise ValueError("custom sessions require a harness and system prompt")
        if self.system_prompt is not None and not self.system_prompt.strip():
            raise ValueError("system prompt must not be blank")
        return self


class AgentRunSummary(ApiModel):
    id: UUID
    status: AgentRunStatus
    cancel_requested_at: datetime | None


class AgentSessionVisibility(RequestModel):
    is_shared: bool


class AgentSessionRead(ApiModel):
    is_shared: bool = False
    can_control: bool = True
    worktree_id: UUID | None = None
    task_id: UUID | None = None
    id: UUID
    project_id: UUID
    agent_version_id: UUID
    agent_kind: PlatformAgentKind
    agent_version: int
    agent_display_name: str
    harness: Literal["codex"] | None
    system_prompt: str | None
    created_by_user_id: UUID
    title: str | None
    status: AgentSessionStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    latest_run: AgentRunSummary | None = None


class AgentMessageCreate(RequestModel):
    client_request_id: UUID
    content_md: str = Field(min_length=1, max_length=200_000)
    gateway_profile_id: UUID
    context_artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def distinct_context(self) -> AgentMessageCreate:
        if len(set(self.context_artifact_ids)) != len(self.context_artifact_ids):
            raise ValueError("duplicate context artifacts")
        return self


class AgentMessageRead(ApiModel):
    id: UUID
    session_id: UUID
    sequence: int
    role: AgentMessageRole
    author_user_id: UUID | None
    content_md: str
    created_at: datetime


class AgentRunRead(ApiModel):
    id: UUID
    session_id: UUID
    project_id: UUID
    request_message_id: UUID | None
    parent_run_id: UUID | None
    queue_sequence: int
    status: AgentRunStatus
    attempt: int
    cancel_requested_at: datetime | None
    deadline_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime


class AgentTurnQueued(BaseModel):
    message: AgentMessageRead
    run: AgentRunRead


class AgentRunResume(RequestModel):
    client_request_id: UUID
    gateway_profile_id: UUID


class AgentRunEventRead(ApiModel):
    run_id: UUID
    cursor: int
    kind: AgentRunEventKind
    payload: dict[str, object]
    occurred_at: datetime


class ExternalCredentialCreate(RequestModel):
    agent_id: UUID
    name: str = Field(min_length=1, max_length=200)


class ExternalCredentialRead(ApiModel):
    secret_reveal_available: bool = False
    agent_id: UUID | None
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

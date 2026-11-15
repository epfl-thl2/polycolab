"""The unified conversation API: human inputs, saved items, and execution metadata."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.conversation import (
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
    ItemStatus,
    MessageRole,
)
from polycolab.entities.enums import AgentRunStatus, PlatformAgentKind, UsageSource


class ConversationCreate(RequestModel):
    worktree_id: UUID | None = None
    project_id: UUID
    agent_kind: PlatformAgentKind
    title: str | None = Field(default=None, max_length=300)
    agent_version: Literal[1, 2, 3] = 3
    harness: Literal["codex"] | None = None
    system_prompt: str | None = Field(default=None, min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def custom_configuration(self) -> ConversationCreate:
        if (self.harness is None) != (self.system_prompt is None):
            raise ValueError("custom conversations require a harness and system prompt")
        if self.system_prompt is not None and not self.system_prompt.strip():
            raise ValueError("system prompt must not be blank")
        return self


class ConversationPatch(RequestModel):
    title: str | None = Field(default=None, max_length=300)
    archived: bool | None = None

    @model_validator(mode="after")
    def has_changes(self) -> ConversationPatch:
        if not self.model_fields_set:
            raise ValueError("at least one metadata field is required")
        return self


class SharingRead(ApiModel):
    mode: ConversationSharing
    can_manage: bool


class SharingPatch(RequestModel):
    mode: ConversationSharing


class ConversationMessage(RequestModel):
    type: Literal["message"]
    client_request_id: UUID
    content_md: str = Field(min_length=1, max_length=200_000)
    provider_connection_id: UUID
    context_artifact_ids: list[UUID] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def distinct_context(self) -> ConversationMessage:
        if len(set(self.context_artifact_ids)) != len(self.context_artifact_ids):
            raise ValueError("duplicate context artifacts")
        return self


class ConversationInterrupt(RequestModel):
    type: Literal["interrupt"]
    run_id: UUID


type ConversationEvent = Annotated[
    ConversationMessage | ConversationInterrupt, Field(discriminator="type")
]


class RunResume(RequestModel):
    client_request_id: UUID
    provider_connection_id: UUID


class AgentConfigurationRead(ApiModel):
    agent_version_id: UUID
    display_name: str
    agent_kind: str
    agent_version: int
    harness: str
    harness_version: str | None
    connection_protocol: str | None
    system_prompt_override: str | None


class WorkingContextRead(ApiModel):
    worktree_id: UUID | None


class HierarchyRead(ApiModel):
    root_id: UUID
    parent_id: UUID | None
    spawning_run_id: UUID | None
    spawning_item_id: UUID | None
    delegated_task: str | None


class TokenObservationRead(ApiModel):
    source: UsageSource
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    observed_at: datetime | None
    execution_id: UUID | None
    event_cursor: int | None


class UsageReservationRead(ApiModel):
    tokens: int
    cost_microusd: int


class UsageRead(ApiModel):
    observations: list[TokenObservationRead]
    reservations: list[UsageReservationRead]


class ExecutionSummaryRead(ApiModel):
    id: UUID
    status: AgentRunStatus | Literal["INTERRUPTED"]
    requested_model: str | None
    observed_model: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    cancel_requested_at: datetime | None
    requested_by_user_id: UUID
    can_interrupt: bool


class ConversationCapabilities(ApiModel):
    can_send: bool
    can_manage: bool
    can_share: bool
    can_stream: bool


class ConversationRead(ApiModel):
    id: UUID
    owner_id: UUID
    project_id: UUID | None
    title: str | None
    origin: ConversationOrigin
    status: ConversationStatus
    sharing: ConversationSharing
    configuration: AgentConfigurationRead | None
    working_context: WorkingContextRead
    hierarchy: HierarchyRead
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    capabilities: ConversationCapabilities
    latest_execution: ExecutionSummaryRead | None
    usage: UsageRead | None


class HumanAuthorRead(ApiModel):
    type: Literal["human"] = "human"
    user_id: UUID


class AgentAuthorRead(ApiModel):
    type: Literal["agent"] = "agent"
    agent_version_id: UUID | None
    display_name: str | None


class ToolAuthorRead(ApiModel):
    type: Literal["tool"] = "tool"
    name: str
    agent_version_id: UUID | None


class SystemAuthorRead(ApiModel):
    type: Literal["system"] = "system"


type ItemAuthorRead = Annotated[
    HumanAuthorRead | AgentAuthorRead | ToolAuthorRead | SystemAuthorRead,
    Field(discriminator="type"),
]


class MessagePayloadRead(ApiModel):
    role: MessageRole
    content_md: str


class ToolCallPayloadRead(ApiModel):
    call_id: str | None
    name: str
    arguments_json: str | None


class ToolResultPayloadRead(ApiModel):
    call_id: str | None
    name: str
    outcome: str
    output_json: str | None


class ErrorPayloadRead(ApiModel):
    code: str


class ItemRead(ApiModel):
    id: UUID
    conversation_id: UUID
    sequence: int
    author: ItemAuthorRead
    execution_id: UUID | None
    created_at: datetime
    status: ItemStatus


class MessageItemRead(ItemRead):
    type: Literal["message"] = "message"
    data: MessagePayloadRead


class ToolCallItemRead(ItemRead):
    type: Literal["tool_call"] = "tool_call"
    data: ToolCallPayloadRead


class ToolResultItemRead(ItemRead):
    type: Literal["tool_result"] = "tool_result"
    data: ToolResultPayloadRead


class ErrorItemRead(ItemRead):
    type: Literal["error"] = "error"
    data: ErrorPayloadRead


type TranscriptItem = Annotated[
    MessageItemRead | ToolCallItemRead | ToolResultItemRead | ErrorItemRead,
    Field(discriminator="type"),
]


class ItemPage(ApiModel):
    items: list[TranscriptItem]
    next_cursor: str | None


class RunRead(ExecutionSummaryRead):
    conversation_id: UUID
    project_id: UUID | None
    origin: ConversationOrigin
    client_request_id: UUID
    request_item_id: UUID | None
    parent_run_id: UUID | None
    queue_sequence: int
    attempt: int | None
    deadline_at: datetime | None
    updated_at: datetime | None
    usage: UsageRead | None
    can_resume: bool
    can_read_private_context: bool


class MessageAccepted(ApiModel):
    type: Literal["message"] = "message"
    item: MessageItemRead
    run: RunRead


class InterruptAccepted(ApiModel):
    type: Literal["interrupt"] = "interrupt"
    run: RunRead


type EventAccepted = Annotated[MessageAccepted | InterruptAccepted, Field(discriminator="type")]

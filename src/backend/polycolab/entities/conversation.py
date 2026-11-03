"""Immutable conversation snapshots, independent of transport and persistence.

Transcript pages and execution summaries are loaded separately. None means a
summary was not loaded, rather than an empty transcript or zero usage. Private
runtime bindings are deliberately not fields on public conversation snapshots.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from polycolab.entities.enums import AgentRunStatus, RuntimeBindingStatus, UsageSource


def safe_failure_code(code: str) -> str:
    """Keep historical diagnostic text out of user-visible failure summaries."""
    if (
        not code
        or len(code) > 100
        or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
            for character in code
        )
    ):
        return "execution_failed"
    return code


class ConversationKind(StrEnum):
    DIRECT = "direct"
    AGENT = "agent"


class ConversationOrigin(StrEnum):
    AGENT = "agent"
    LEGACY_DIRECT = "legacy_direct"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationSharing(StrEnum):
    PRIVATE = "private"
    PROJECT_READABLE = "project_readable"
    PROJECT_CONTRIBUTABLE = "project_contributable"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ItemStatus(StrEnum):
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    IN_PROGRESS = "in_progress"


class ItemVisibility(StrEnum):
    USER_VISIBLE = "user_visible"
    MODEL_ONLY = "model_only"


@dataclass(frozen=True)
class AgentConfiguration:
    agent_version_id: UUID
    display_name: str
    agent_kind: str
    agent_version: int
    harness: str
    harness_version: str | None = None
    connection_protocol: str | None = None
    system_prompt_override: str | None = None

    def __post_init__(self) -> None:
        if not self.harness.strip():
            raise ValueError("harness must not be blank")
        if self.agent_version < 1:
            raise ValueError("agent version must be positive")


@dataclass(frozen=True)
class WorkingContext:
    task_id: UUID | None = None
    worktree_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.task_id and self.worktree_id and self.task_id != self.worktree_id:
            raise ValueError("task and worktree references must agree")


@dataclass(frozen=True)
class ConversationHierarchy:
    root_id: UUID
    parent_id: UUID | None = None
    spawning_run_id: UUID | None = None
    spawning_item_id: UUID | None = None
    delegated_task: str | None = None

    def __post_init__(self) -> None:
        if self.parent_id is None and any(
            value is not None
            for value in (self.spawning_run_id, self.spawning_item_id, self.delegated_task)
        ):
            raise ValueError("only child conversations may have spawning context")


@dataclass(frozen=True)
class ExecutionContext:
    """Exact references selected for this execution, never mutable latest aliases."""

    artifact_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        for references in (self.artifact_ids,):
            if not isinstance(references, tuple) or len(references) != len(set(references)):
                raise ValueError("execution references must be distinct immutable tuples")


@dataclass(frozen=True)
class ExecutionSummary:
    id: UUID
    status: AgentRunStatus | Literal["INTERRUPTED"]
    requested_model: str | None
    observed_model: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None

    def __post_init__(self) -> None:
        if (
            self.failure_code is not None
            and safe_failure_code(self.failure_code) != self.failure_code
        ):
            raise ValueError("execution summaries require a safe failure code")


@dataclass(frozen=True)
class TokenObservation:
    source: UsageSource
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    observed_at: datetime | None = None
    execution_id: UUID | None = None
    event_cursor: int | None = None

    def __post_init__(self) -> None:
        if any(
            value is not None and value < 0
            for value in (self.input_tokens, self.output_tokens, self.total_tokens)
        ):
            raise ValueError("token observations must be non-negative")
        if self.event_cursor is not None and (self.event_cursor < 1 or self.execution_id is None):
            raise ValueError("event provenance requires an execution and positive cursor")


@dataclass(frozen=True)
class UsageReservation:
    tokens: int
    cost_microusd: int

    def __post_init__(self) -> None:
        if self.tokens < 0 or self.cost_microusd < 0:
            raise ValueError("reservations must be non-negative")


@dataclass(frozen=True)
class UsageSummary:
    observations: tuple[TokenObservation, ...]
    reservations: tuple[UsageReservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.observations, tuple) or not isinstance(self.reservations, tuple):
            raise ValueError("usage collections must be immutable tuples")


@dataclass(frozen=True)
class ConversationExecution:
    """Publicly inspectable execution state, without leases, grants or credentials."""

    conversation_id: UUID
    project_id: UUID | None
    requested_by_user_id: UUID
    request_id: UUID
    request_item_id: UUID | None
    parent_run_id: UUID | None
    sequence: int
    origin: ConversationOrigin
    summary: ExecutionSummary
    attempt: int | None
    cancel_requested_at: datetime | None
    deadline_at: datetime | None
    updated_at: datetime | None
    context: ExecutionContext | None
    usage: UsageSummary | None = None

    def __post_init__(self) -> None:
        if self.sequence < 1 or (self.attempt is not None and self.attempt < 0):
            raise ValueError("invalid execution sequence or attempt")

    @property
    def id(self) -> UUID:
        return self.summary.id


@dataclass(frozen=True)
class PrivateRuntimeBinding:
    id: UUID
    conversation_id: UUID
    adapter: str
    external_session_reference: str | None
    status: RuntimeBindingStatus
    created_at: datetime
    ended_at: datetime | None


@dataclass(frozen=True)
class Conversation:
    id: UUID
    owner_id: UUID
    project_id: UUID | None
    title: str | None
    created_at: datetime
    updated_at: datetime
    hierarchy: ConversationHierarchy
    origin: ConversationOrigin = ConversationOrigin.LEGACY_DIRECT
    status: ConversationStatus = ConversationStatus.ACTIVE
    sharing: ConversationSharing = ConversationSharing.PRIVATE
    archived_at: datetime | None = None
    configuration: AgentConfiguration | None = None
    working_context: WorkingContext = WorkingContext()
    latest_execution: ExecutionSummary | None = None
    usage: UsageSummary | None = None

    def __post_init__(self) -> None:
        if self.hierarchy.parent_id is None and self.hierarchy.root_id != self.id:
            raise ValueError("root conversations must reference themselves")
        if self.hierarchy.parent_id is not None and (
            self.hierarchy.parent_id == self.id or self.hierarchy.root_id == self.id
        ):
            raise ValueError("a child cannot be its own parent or root")
        if self.project_id is None and self.sharing is not ConversationSharing.PRIVATE:
            raise ValueError("standalone conversations must be private")
        if self.origin is ConversationOrigin.LEGACY_DIRECT and (
            self.configuration is not None or self.sharing is not ConversationSharing.PRIVATE
        ):
            raise ValueError("legacy direct history cannot enable agents or sharing")
        if self.origin is ConversationOrigin.AGENT and self.configuration is None:
            raise ValueError("agent conversations require pinned configuration")

    @property
    def kind(self) -> ConversationKind:
        return (
            ConversationKind.AGENT
            if self.origin is ConversationOrigin.AGENT
            else ConversationKind.DIRECT
        )

    @property
    def is_shared(self) -> bool:
        return self.sharing is not ConversationSharing.PRIVATE


@dataclass(frozen=True)
class HumanAuthor:
    user_id: UUID


@dataclass(frozen=True)
class AgentAuthor:
    """Unknown historical attribution remains absent, never guessed."""

    agent_version_id: UUID | None
    display_name: str | None = None


@dataclass(frozen=True)
class ToolAuthor:
    name: str
    agent_version_id: UUID | None = None


@dataclass(frozen=True)
class SystemAuthor:
    pass


type ItemAuthor = HumanAuthor | AgentAuthor | ToolAuthor | SystemAuthor


@dataclass(frozen=True)
class MessageData:
    role: MessageRole
    content_md: str


@dataclass(frozen=True)
class ToolCallData:
    """Stored invocation metadata; historical events omit arguments."""

    call_id: str | None
    name: str
    arguments_json: str | None = None

    def __post_init__(self) -> None:
        if self.call_id == "" or not self.name:
            raise ValueError("tool calls require a call ID and name")


@dataclass(frozen=True)
class ToolResultData:
    call_id: str | None
    name: str
    outcome: str
    output_json: str | None = None

    def __post_init__(self) -> None:
        if self.call_id == "" or not self.name or not self.outcome:
            raise ValueError("tool results require a call ID, name and outcome")


@dataclass(frozen=True)
class ErrorData:
    code: str

    def __post_init__(self) -> None:
        if safe_failure_code(self.code) != self.code:
            raise ValueError("errors require a safe code, not diagnostic text")


type ConversationItemData = MessageData | ToolCallData | ToolResultData | ErrorData


@dataclass(frozen=True)
class ConversationItem[Data: ConversationItemData]:
    """A materialized transcript item; sequence belongs to its conversation."""

    id: UUID
    conversation_id: UUID
    sequence: int
    author: ItemAuthor
    data: Data
    created_at: datetime
    execution_id: UUID | None = None
    status: ItemStatus = ItemStatus.COMPLETED
    visibility: ItemVisibility = ItemVisibility.USER_VISIBLE

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("item sequence must be positive")
        if isinstance(self.data, MessageData):
            expected = {
                MessageRole.USER: HumanAuthor,
                MessageRole.ASSISTANT: AgentAuthor,
                MessageRole.SYSTEM: SystemAuthor,
            }[self.data.role]
            if not isinstance(self.author, expected):
                raise ValueError("message role must match authorship")
        elif isinstance(self.data, ToolCallData):
            if not isinstance(self.author, AgentAuthor):
                raise ValueError("tool calls must be agent authored")
        elif isinstance(self.data, ToolResultData):
            if not isinstance(self.author, ToolAuthor) or self.author.name != self.data.name:
                raise ValueError("tool results must identify their tool author")
        elif not isinstance(self.data, ErrorData):
            raise TypeError("Unsupported conversation item payload")

    @property
    def author_user_id(self) -> UUID | None:
        return self.author.user_id if isinstance(self.author, HumanAuthor) else None

    @property
    def type(self) -> Literal["message", "tool_call", "tool_result", "error"]:
        match self.data:
            case MessageData():
                return "message"
            case ToolCallData():
                return "tool_call"
            case ToolResultData():
                return "tool_result"
            case ErrorData():
                return "error"
        raise TypeError("Unsupported conversation item payload")


@dataclass(frozen=True)
class LegacyExecution:
    id: UUID
    conversation_id: UUID
    request_id: UUID
    sequence: int
    profile_id: UUID
    model_id: str
    status: Literal["completed", "failed", "interrupted"]
    failure_code: str | None
    created_at: datetime
    usage: UsageSummary

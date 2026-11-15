"""SQLAlchemy entities owned by the agents capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.elements import ColumnElement

from polycolab.db.base import Base
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    ExecutionProfile,
    PlatformAgentKind,
    RuntimeBindingStatus,
    RuntimeRunBindingStatus,
    StoredConversationStatus,
    UsageSource,
)
from polycolab.entities.time import utc_now


def _root_id(context: DefaultExecutionContext) -> UUID:
    assert context.current_parameters is not None
    return UUID(str(context.current_parameters["id"]))


class SqlPlatformAgentVersion(Base):
    """An immutable, platform-controlled agent definition pinned by sessions and runs."""

    __tablename__ = "platform_agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_kind", "version", name="uq_platform_agent_versions_kind_version"),
        CheckConstraint(
            "agent_kind IN ('RESEARCHER', 'CRITIC')", name="ck_platform_agent_versions_kind"
        ),
        CheckConstraint(
            "execution_profile IN ('TRUSTED_HOSTED')",
            name="ck_platform_agent_versions_execution_profile",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_kind: Mapped[PlatformAgentKind] = mapped_column(
        Enum(PlatformAgentKind, native_enum=False, length=32)
    )
    version: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(200))
    instructions_text: Mapped[str] = mapped_column(Text)
    instructions_digest: Mapped[str] = mapped_column(String(64), unique=True)
    execution_profile: Mapped[ExecutionProfile] = mapped_column(
        Enum(ExecutionProfile, native_enum=False, length=32),
        default=ExecutionProfile.TRUSTED_HOSTED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlConversation(Base):
    """Long-lived project chat state, distinct from transient worker executions."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_conversations_id_project"),
        CheckConstraint("origin IN ('agent', 'legacy_direct')", name="ck_conversations_origin"),
        CheckConstraint(
            "sharing IN ('private', 'members_can_view', 'members_can_participate')",
            name="ck_conversations_sharing",
        ),
        CheckConstraint(
            "(parent_id IS NULL AND root_id = id) OR "
            "(parent_id IS NOT NULL AND parent_id != id AND root_id != id)",
            name="ck_conversations_hierarchy",
        ),
        CheckConstraint("next_message_sequence >= 0", name="ck_conversations_message_sequence"),
        CheckConstraint("next_run_sequence >= 0", name="ck_conversations_run_sequence"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_conversations_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    worktree_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("worktrees.id"), nullable=True, index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    origin: Mapped[str] = mapped_column(String(24), default="agent", server_default="agent")
    sharing: Mapped[str] = mapped_column(String(24), default="private", server_default="private")
    root_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), default=_root_id)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversations.id"))
    spawning_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    spawning_item_id: Mapped[UUID | None] = mapped_column(nullable=True)
    delegated_task: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    configuration: Mapped[SqlConversationConfiguration | None] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        uselist=False,
    )

    @property
    def agent_version_id(self) -> UUID:
        if self.configuration is None:
            raise ValueError("conversation has no agent configuration")
        return self.configuration.agent_version_id

    @property
    def harness(self) -> str | None:
        if self.configuration is None or self.configuration.harness == "platform":
            return None
        return self.configuration.harness

    @property
    def system_prompt(self) -> str | None:
        return self.configuration.system_prompt if self.configuration else None

    status: Mapped[StoredConversationStatus] = mapped_column(
        Enum(StoredConversationStatus, native_enum=False, length=16),
        default=StoredConversationStatus.ACTIVE,
    )
    next_message_sequence: Mapped[int] = mapped_column(Integer, default=0)
    next_run_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @hybrid_property
    def is_shared(self) -> bool:
        return self.sharing in {"members_can_view", "members_can_participate"}

    @is_shared.inplace.setter
    def _set_shared(self, value: bool) -> None:
        self.sharing = "members_can_view" if value else "private"

    @is_shared.inplace.expression
    @classmethod
    def _shared_expression(cls) -> ColumnElement[bool]:
        return cls.sharing != "private"


class SqlConversationConfiguration(Base):
    """Pinned creation-time identity and harness selection, separate from execution state."""

    __tablename__ = "conversation_configurations"
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_agent_versions.id"), index=True
    )
    agent_display_name: Mapped[str] = mapped_column(String(200))
    agent_kind: Mapped[str] = mapped_column(String(32))
    agent_version: Mapped[int] = mapped_column(Integer)
    harness: Mapped[str] = mapped_column(String(100))
    harness_version: Mapped[str | None] = mapped_column(String(100))
    connection_protocol: Mapped[str | None] = mapped_column(String(100))
    system_prompt: Mapped[str | None] = mapped_column(Text)


class SqlConversationItem(Base):
    """Append-only product-visible message transcript entry."""

    __tablename__ = "conversation_items"
    __table_args__ = (
        UniqueConstraint("id", "conversation_id", name="uq_conversation_items_id_conversation"),
        UniqueConstraint(
            "conversation_id", "sequence", name="uq_conversation_items_conversation_sequence"
        ),
        CheckConstraint("sequence > 0", name="ck_conversation_items_sequence"),
        CheckConstraint(
            "item_type IN ('message', 'tool_call', 'tool_result', 'error')",
            name="ck_conversation_items_type",
        ),
        CheckConstraint(
            "status IN ('completed', 'interrupted', 'in_progress')",
            name="ck_conversation_items_status",
        ),
        CheckConstraint(
            "visibility IN ('user_visible', 'model_only')", name="ck_conversation_items_visibility"
        ),
        CheckConstraint("role IN ('USER', 'AGENT', 'SYSTEM')", name="ck_conversation_items_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[AgentMessageRole] = mapped_column(
        Enum(AgentMessageRole, native_enum=False, length=16)
    )
    author_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_version_id: Mapped[UUID | None] = mapped_column(ForeignKey("platform_agent_versions.id"))
    execution_id: Mapped[UUID | None] = mapped_column(nullable=True)
    item_type: Mapped[str] = mapped_column(String(16), default="message", server_default="message")
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    visibility: Mapped[str] = mapped_column(
        String(16), default="user_visible", server_default="user_visible"
    )
    payload: Mapped[dict[str, object] | None] = mapped_column(JSON)
    content_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAgentRun(Base):
    """Durable execution intent and worker lease; no provider credential is stored here."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("id", "conversation_id", name="uq_agent_runs_id_conversation"),
        UniqueConstraint(
            "id",
            "project_id",
            "requested_by_user_id",
            "agent_version_id",
            name="uq_agent_runs_scope",
        ),
        UniqueConstraint(
            "id",
            "conversation_id",
            "project_id",
            "requested_by_user_id",
            "agent_version_id",
            name="uq_agent_runs_full_scope",
        ),
        UniqueConstraint("request_message_id", name="uq_agent_runs_request_message"),
        UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_agent_runs_client_request"
        ),
        UniqueConstraint(
            "conversation_id", "queue_sequence", name="uq_agent_runs_conversation_queue"
        ),
        ForeignKeyConstraint(
            ["conversation_id", "project_id"],
            ["conversations.id", "conversations.project_id"],
            name="fk_agent_runs_conversation_project",
        ),
        ForeignKeyConstraint(
            ["request_message_id", "conversation_id"],
            ["conversation_items.id", "conversation_items.conversation_id"],
            name="fk_agent_runs_request_message_conversation",
        ),
        CheckConstraint("queue_sequence > 0", name="ck_agent_runs_queue_sequence"),
        CheckConstraint("input_message_sequence > 0", name="ck_agent_runs_input_message_sequence"),
        CheckConstraint("attempt >= 0", name="ck_agent_runs_attempt"),
        CheckConstraint("lease_generation >= 0", name="ck_agent_runs_lease_generation"),
        CheckConstraint("next_event_cursor >= 0", name="ck_agent_runs_event_cursor"),
        CheckConstraint(
            "status IN ('QUEUED', 'CLAIMED', 'RUNNING', 'CANCELLING', "
            "'COMPLETED', 'CANCELLED', 'FAILED', 'TIMED_OUT')",
            name="ck_agent_runs_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    project_id: Mapped[UUID] = mapped_column(index=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_agent_versions.id"), index=True
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    request_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    client_request_id: Mapped[UUID] = mapped_column(index=True, default=uuid4)
    parent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    provider_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_connections.id"), index=True
    )
    gateway_credential_version: Mapped[int] = mapped_column(Integer)
    gateway_model_id: Mapped[str] = mapped_column(String(500))
    runtime_spec: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    queue_sequence: Mapped[int] = mapped_column(Integer)
    input_message_sequence: Mapped[int] = mapped_column(Integer)
    requested_context_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, native_enum=False, length=16), default=AgentRunStatus.QUEUED
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_event_cursor: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlAgentRunEvent(Base):
    """Normalized event ordered by a canonical per-run cursor."""

    __tablename__ = "agent_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "cursor", name="uq_agent_run_events_run_cursor"),
        UniqueConstraint("run_id", "idempotency_key", name="uq_agent_run_events_run_key"),
        CheckConstraint("cursor > 0", name="ck_agent_run_events_cursor"),
        CheckConstraint(
            "kind IN ('RUN_STARTED', 'ASSISTANT_DELTA', 'ASSISTANT_MESSAGE_COMPLETED', "
            "'USAGE_REPORTED', 'CANCEL_REQUESTED', 'RUN_COMPLETED', 'RUN_CANCELLED', "
            "'RUN_FAILED', 'RUN_TIMED_OUT', 'RUNNER_LOST', 'TOOL_REQUESTED', 'TOOL_RESULT')",
            name="ck_agent_run_events_kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    cursor: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[AgentRunEventKind] = mapped_column(
        Enum(AgentRunEventKind, native_enum=False, length=32)
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAgentRunUsage(Base):
    """Append-only normalized metering observations, without provider payloads."""

    __tablename__ = "agent_run_usage"
    __table_args__ = (
        UniqueConstraint("run_id", "event_cursor", name="uq_agent_run_usage_event"),
        ForeignKeyConstraint(
            ["run_id", "event_cursor"],
            ["agent_run_events.run_id", "agent_run_events.cursor"],
            name="fk_agent_run_usage_event",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_agent_run_usage_input"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_agent_run_usage_output"
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="ck_agent_run_usage_total"
        ),
        CheckConstraint(
            "source IN ('PROVIDER_REPORTED', 'ESTIMATED', 'UNKNOWN')",
            name="ck_agent_run_usage_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    event_cursor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[UsageSource] = mapped_column(Enum(UsageSource, native_enum=False, length=32))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExecutionRateWindow(Base):
    """Short-lived admission counters; no prompt, credential, or raw IP is retained."""

    __tablename__ = "execution_rate_windows"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "window_started_at", name="uq_execution_rate_window"),
        CheckConstraint(
            "scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip', "
            "'login_ip', 'login_username')",
            name="ck_execution_rate_window_scope",
        ),
        CheckConstraint("count >= 0", name="ck_execution_rate_window_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[UUID] = mapped_column(index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class SqlOperationalMetricAggregate(Base):
    """Content-free metrics emitted by any API or worker process.

    Rows use a fixed metric/label allowlist in ``polycolab.platform.observability``.  This is
    deliberately an aggregate rather than an event log: it lets the API's
    operator-only scrape endpoint see worker telemetry without retaining
    prompts, provider details, project/user identifiers, or event bodies.
    """

    __tablename__ = "operational_metric_aggregates"
    __table_args__ = (
        UniqueConstraint("metric_name", "labels_key", name="uq_operational_metric_series"),
        CheckConstraint("length(metric_name) <= 128", name="ck_operational_metric_name_length"),
        CheckConstraint("length(labels_key) <= 256", name="ck_operational_metric_labels_length"),
        CheckConstraint("counter_value >= 0", name="ck_operational_metric_counter_nonnegative"),
        CheckConstraint("observation_count >= 0", name="ck_operational_metric_count_nonnegative"),
        CheckConstraint("observation_sum >= 0", name="ck_operational_metric_sum_nonnegative"),
        CheckConstraint("observation_max >= 0", name="ck_operational_metric_max_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    metric_name: Mapped[str] = mapped_column(String(128))
    labels_key: Mapped[str] = mapped_column(String(256))
    labels: Mapped[dict[str, str]] = mapped_column(JSON)
    counter_value: Mapped[int] = mapped_column(BigInteger, default=0)
    observation_count: Mapped[int] = mapped_column(BigInteger, default=0)
    observation_sum: Mapped[float] = mapped_column(Float, default=0.0)
    observation_max: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlOperatorDiagnosticAccess(Base):
    """Tamper-evident-enough application audit trail for operator run views.

    The OIDC subject is salted into a one-way digest before persistence, so the
    audit can correlate access by the same configured operator without storing
    an identity claim alongside private execution state.
    """

    __tablename__ = "operator_diagnostic_accesses"
    __table_args__ = (
        CheckConstraint(
            "length(operator_subject_digest) = 64",
            name="ck_operator_diagnostic_access_subject_digest",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    operator_subject_digest: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[UUID] = mapped_column(index=True)
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRuntimeSessionBinding(Base):
    """Private historical adapter mapping; it is never a browser contract."""

    __tablename__ = "runtime_session_bindings"
    __table_args__ = (
        UniqueConstraint(
            "id", "conversation_id", name="uq_runtime_session_bindings_id_conversation"
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')",
            name="ck_runtime_session_bindings_status",
        ),
        Index(
            "uq_runtime_session_bindings_active_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    adapter_name: Mapped[str] = mapped_column(String(100))
    opaque_runtime_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[RuntimeBindingStatus] = mapped_column(
        Enum(RuntimeBindingStatus, native_enum=False, length=16),
        default=RuntimeBindingStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlRuntimeRunBinding(Base):
    """Private mapping of one canonical run to a concrete adapter execution."""

    __tablename__ = "runtime_run_bindings"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_runtime_run_bindings_run"),
        ForeignKeyConstraint(
            ["run_id", "conversation_id"],
            ["agent_runs.id", "agent_runs.conversation_id"],
            name="fk_runtime_run_bindings_run_conversation",
        ),
        ForeignKeyConstraint(
            ["session_binding_id", "conversation_id"],
            ["runtime_session_bindings.id", "runtime_session_bindings.conversation_id"],
            name="fk_runtime_run_bindings_session_binding",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'FINISHED', 'LOST')",
            name="ck_runtime_run_bindings_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(index=True)
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    session_binding_id: Mapped[UUID] = mapped_column(index=True)
    adapter_name: Mapped[str] = mapped_column(String(100))
    opaque_runtime_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[RuntimeRunBindingStatus] = mapped_column(
        Enum(RuntimeRunBindingStatus, native_enum=False, length=16),
        default=RuntimeRunBindingStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlContextManifest(Base):
    """Immutable, permission-filtered project artifact selection for one run."""

    __tablename__ = "context_manifests"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_context_manifests_run"),
        UniqueConstraint(
            "id",
            "run_id",
            "project_id",
            "requested_by_user_id",
            "agent_version_id",
            name="uq_context_manifests_scope",
        ),
        ForeignKeyConstraint(
            ["run_id", "project_id", "requested_by_user_id", "agent_version_id"],
            [
                "agent_runs.id",
                "agent_runs.project_id",
                "agent_runs.requested_by_user_id",
                "agent_runs.agent_version_id",
            ],
            name="fk_context_manifests_run_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("platform_agent_versions.id"))
    artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlContextManifestArtifact(Base):
    """Typed artifact member mirroring an immutable context manifest identity."""

    __tablename__ = "context_manifest_artifacts"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_context_manifest_artifact_position"),
        UniqueConstraint("manifest_id", "position", name="uq_context_manifest_artifact_position"),
    )

    manifest_id: Mapped[UUID] = mapped_column(ForeignKey("context_manifests.id"), primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(
        ForeignKey("artifacts.id"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer)


class SqlRunToolCapability(Base):
    """One-run gateway capability; only its digest and stable scope IDs persist."""

    __tablename__ = "run_tool_capabilities"
    __table_args__ = (
        CheckConstraint("lease_generation >= 0", name="ck_run_tool_capabilities_lease_generation"),
        ForeignKeyConstraint(
            ["context_manifest_id", "run_id", "project_id", "user_id", "agent_version_id"],
            [
                "context_manifests.id",
                "context_manifests.run_id",
                "context_manifests.project_id",
                "context_manifests.requested_by_user_id",
                "context_manifests.agent_version_id",
            ],
            name="fk_run_tool_capabilities_manifest_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("platform_agent_versions.id"))
    context_manifest_id: Mapped[UUID] = mapped_column(ForeignKey("context_manifests.id"))
    allowed_tools: Mapped[list[str]] = mapped_column(JSON)
    lease_generation: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlPlatformAgentVersion",
    "SqlConversation",
    "SqlConversationItem",
    "SqlAgentRun",
    "SqlAgentRunEvent",
    "SqlAgentRunUsage",
    "SqlExecutionRateWindow",
    "SqlOperationalMetricAggregate",
    "SqlOperatorDiagnosticAccess",
    "SqlRuntimeSessionBinding",
    "SqlRuntimeRunBinding",
    "SqlContextManifest",
    "SqlContextManifestArtifact",
    "SqlRunToolCapability",
]


class SqlHostedExecutor(Base):
    """Short-lived host advertisement, separate from attempt leases."""

    __tablename__ = "hosted_executors"
    __table_args__ = (
        CheckConstraint("capacity BETWEEN 0 AND 64", name="hosted_executors_capacity_check"),
    )
    incarnation: Mapped[str] = mapped_column(String(36), default="legacy")
    protocol_version: Mapped[int] = mapped_column(Integer, default=7)
    sandbox_backend: Mapped[str] = mapped_column(
        String(16), default="microsandbox", server_default="microsandbox"
    )
    sandbox_version: Mapped[str] = mapped_column(
        String(128), default="0.6.18", server_default="0.6.18"
    )
    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    image_digest: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SqlHostedRunArtifact(Base):
    """Private artifact exports from a hosted session."""

    __tablename__ = "hosted_run_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "generation", "path", name="uq_hosted_export_path"),
    )
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(240))
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlHostedCompletion(Base):
    __tablename__ = "hosted_completions"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(200))
    payload_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlHostedSlot(Base):
    __tablename__ = "hosted_slots"
    __table_args__ = (
        CheckConstraint("ordinal BETWEEN 0 AND 63", name="hosted_slots_ordinal_check"),
        CheckConstraint("(run_id IS NULL) = (generation IS NULL)", name="hosted_slots_check"),
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("hosted_executors.worker_id"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    generation: Mapped[int | None] = mapped_column(Integer, nullable=True)

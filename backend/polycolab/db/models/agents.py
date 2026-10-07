"""SQLAlchemy entities owned by the agents capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
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
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    AgentSessionStatus,
    ExecutionProfile,
    PlatformAgentKind,
    ProposalChangeStatus,
    ProposalChangeType,
    ProposalDecisionAction,
    RuntimeBindingStatus,
    RuntimeRunBindingStatus,
    UsageSource,
)
from polycolab.entities.time import utc_now


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


class SqlAgentSession(Base):
    """Long-lived project chat state, distinct from transient worker executions."""

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("id", "project_id", name="uq_agent_sessions_id_project"),
        CheckConstraint("next_message_sequence >= 0", name="ck_agent_sessions_message_sequence"),
        CheckConstraint("next_run_sequence >= 0", name="ck_agent_sessions_run_sequence"),
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED')", name="ck_agent_sessions_status"),
        CheckConstraint(
            "(harness IS NULL AND system_prompt IS NULL) OR "
            "(harness = 'codex' AND system_prompt IS NOT NULL)",
            name="ck_agent_sessions_custom_configuration",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspace_tasks.id"), nullable=True, index=True
    )
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_agent_versions.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    harness: Mapped[Literal["codex"] | None] = mapped_column(String(32), nullable=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentSessionStatus] = mapped_column(
        Enum(AgentSessionStatus, native_enum=False, length=16), default=AgentSessionStatus.ACTIVE
    )
    next_message_sequence: Mapped[int] = mapped_column(Integer, default=0)
    next_run_sequence: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlAgentMessage(Base):
    """Append-only product-visible message transcript entry."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_agent_messages_id_session"),
        UniqueConstraint("session_id", "sequence", name="uq_agent_messages_session_sequence"),
        CheckConstraint("sequence > 0", name="ck_agent_messages_sequence"),
        CheckConstraint("role IN ('USER', 'AGENT', 'SYSTEM')", name="ck_agent_messages_role"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    role: Mapped[AgentMessageRole] = mapped_column(
        Enum(AgentMessageRole, native_enum=False, length=16)
    )
    author_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    content_md: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAgentRun(Base):
    """Durable execution intent and worker lease; no provider credential is stored here."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("id", "session_id", name="uq_agent_runs_id_session"),
        UniqueConstraint(
            "id",
            "project_id",
            "requested_by_user_id",
            "agent_version_id",
            name="uq_agent_runs_scope",
        ),
        UniqueConstraint(
            "id",
            "session_id",
            "project_id",
            "requested_by_user_id",
            "agent_version_id",
            name="uq_agent_runs_full_scope",
        ),
        UniqueConstraint("request_message_id", name="uq_agent_runs_request_message"),
        UniqueConstraint("session_id", "client_request_id", name="uq_agent_runs_client_request"),
        UniqueConstraint("session_id", "queue_sequence", name="uq_agent_runs_session_queue"),
        ForeignKeyConstraint(
            ["session_id", "project_id"],
            ["agent_sessions.id", "agent_sessions.project_id"],
            name="fk_agent_runs_session_project",
        ),
        ForeignKeyConstraint(
            ["request_message_id", "session_id"],
            ["agent_messages.id", "agent_messages.session_id"],
            name="fk_agent_runs_request_message_session",
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
    session_id: Mapped[UUID] = mapped_column(index=True)
    project_id: Mapped[UUID] = mapped_column(index=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_agent_versions.id"), index=True
    )
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    request_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    client_request_id: Mapped[UUID] = mapped_column(index=True, default=uuid4)
    parent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    gateway_profile_id: Mapped[UUID] = mapped_column(ForeignKey("gateway_profiles.id"), index=True)
    gateway_credential_version: Mapped[int] = mapped_column(Integer)
    gateway_model_id: Mapped[str] = mapped_column(String(500))
    runtime_spec: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    queue_sequence: Mapped[int] = mapped_column(Integer)
    input_message_sequence: Mapped[int] = mapped_column(Integer)
    requested_context_revision_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
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
        UniqueConstraint("id", "session_id", name="uq_runtime_session_bindings_id_session"),
        CheckConstraint(
            "status IN ('ACTIVE', 'SUPERSEDED', 'ARCHIVED')",
            name="ck_runtime_session_bindings_status",
        ),
        Index(
            "uq_runtime_session_bindings_active_session",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
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
            ["run_id", "session_id"],
            ["agent_runs.id", "agent_runs.session_id"],
            name="fk_runtime_run_bindings_run_session",
        ),
        ForeignKeyConstraint(
            ["session_binding_id", "session_id"],
            ["runtime_session_bindings.id", "runtime_session_bindings.session_id"],
            name="fk_runtime_run_bindings_session_binding",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'FINISHED', 'LOST')",
            name="ck_runtime_run_bindings_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(index=True)
    session_id: Mapped[UUID] = mapped_column(index=True)
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
    """Immutable, permission-filtered exact revisions supplied to one run."""

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
    revision_ids: Mapped[list[str]] = mapped_column(JSON)
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


class SqlRunWriteGrant(Base):
    """Immutable requested authority; effective rights are recomputed on every call."""

    __tablename__ = "run_write_grants"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    request: Mapped[dict[str, object]] = mapped_column(JSON)
    request_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRunRevisionOutput(Base):
    """Exact run-created outputs, separate from the immutable input manifest."""

    __tablename__ = "run_revision_outputs"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRunArtifactOutput(Base):
    """Exact committed verification outputs attributable to one agent run."""

    __tablename__ = "run_artifact_outputs"
    __table_args__ = (UniqueConstraint("artifact_id", name="uq_run_artifact_output_artifact"),)

    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    result_id: Mapped[UUID] = mapped_column(ForeignKey("verification_results.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("platform_agent_versions.id"))
    context_manifest_id: Mapped[UUID] = mapped_column(ForeignKey("context_manifests.id"))
    allowed_tools: Mapped[list[str]] = mapped_column(JSON)
    lease_generation: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlProposal(Base):
    """Unaccepted agent output, deliberately separate from canonical research."""

    __tablename__ = "proposals"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_proposals_run_key"),
        UniqueConstraint("id", "project_id", name="uq_proposals_id_project"),
        ForeignKeyConstraint(
            [
                "context_manifest_id",
                "run_id",
                "project_id",
                "requested_by_user_id",
                "agent_version_id",
            ],
            [
                "context_manifests.id",
                "context_manifests.run_id",
                "context_manifests.project_id",
                "context_manifests.requested_by_user_id",
                "context_manifests.agent_version_id",
            ],
            name="fk_proposals_manifest_scope",
        ),
        ForeignKeyConstraint(
            ["session_id", "project_id"],
            ["agent_sessions.id", "agent_sessions.project_id"],
            name="fk_proposals_session_project",
        ),
        ForeignKeyConstraint(
            ["run_id", "session_id", "project_id", "requested_by_user_id", "agent_version_id"],
            [
                "agent_runs.id",
                "agent_runs.session_id",
                "agent_runs.project_id",
                "agent_runs.requested_by_user_id",
                "agent_runs.agent_version_id",
            ],
            name="fk_proposals_run_session_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), index=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    agent_version_id: Mapped[UUID] = mapped_column(ForeignKey("platform_agent_versions.id"))
    context_manifest_id: Mapped[UUID] = mapped_column(ForeignKey("context_manifests.id"))
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlProposalChange(Base):
    __tablename__ = "proposal_changes"
    __table_args__ = (
        UniqueConstraint("proposal_id", "ordinal", name="uq_proposal_changes_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_proposal_changes_ordinal"),
        CheckConstraint(
            "change_type IN ('CREATE_OBJECT', 'CREATE_REVISION', 'CREATE_RELATION', "
            "'CREATE_COMMENT')",
            name="ck_proposal_changes_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REJECTED')",
            name="ck_proposal_changes_status",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND decided_by_user_id IS NULL AND decided_at IS NULL "
            "AND applied_entity_id IS NULL) OR "
            "(status = 'REJECTED' AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL "
            "AND applied_entity_id IS NULL) OR "
            "(status = 'ACCEPTED' AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL "
            "AND applied_entity_id IS NOT NULL)",
            name="ck_proposal_changes_decision",
        ),
        UniqueConstraint("id", "project_id", name="uq_proposal_changes_id_project"),
        ForeignKeyConstraint(
            ["proposal_id", "project_id"],
            ["proposals.id", "proposals.project_id"],
            name="fk_proposal_changes_proposal_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    change_type: Mapped[ProposalChangeType] = mapped_column(
        Enum(ProposalChangeType, native_enum=False, length=32)
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    status: Mapped[ProposalChangeStatus] = mapped_column(
        Enum(ProposalChangeStatus, native_enum=False, length=16),
        default=ProposalChangeStatus.PENDING,
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_entity_id: Mapped[UUID | None] = mapped_column(nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_cursors: Mapped[list[int]] = mapped_column(JSON, default=list)


class SqlProposalChangeDecision(Base):
    """One immutable human decision and its replay-safe request identity."""

    __tablename__ = "proposal_change_decisions"
    __table_args__ = (
        UniqueConstraint("proposal_change_id", name="uq_proposal_change_decisions_change"),
        UniqueConstraint(
            "proposal_change_id",
            "idempotency_key_digest",
            name="uq_proposal_change_decisions_change_key",
        ),
        CheckConstraint(
            "action IN ('ACCEPT', 'REJECT')", name="ck_proposal_change_decisions_action"
        ),
        CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_digest) = 64",
            name="ck_proposal_change_decisions_digest_length",
        ),
        ForeignKeyConstraint(
            ["proposal_change_id", "project_id"],
            ["proposal_changes.id", "proposal_changes.project_id"],
            name="fk_proposal_change_decisions_change_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_change_id: Mapped[UUID] = mapped_column(ForeignKey("proposal_changes.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    action: Mapped[ProposalDecisionAction] = mapped_column(
        Enum(ProposalDecisionAction, native_enum=False, length=16)
    )
    idempotency_key_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    decided_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlProposalDecisionBatch(Base):
    """One all-or-nothing review request, retained only as an idempotency record."""

    __tablename__ = "proposal_decision_batches"
    __table_args__ = (
        UniqueConstraint(
            "proposal_id", "idempotency_key_digest", name="uq_proposal_decision_batches_key"
        ),
        CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_digest) = 64",
            name="ck_proposal_decision_batches_digest_length",
        ),
        ForeignKeyConstraint(
            ["proposal_id", "project_id"],
            ["proposals.id", "proposals.project_id"],
            name="fk_proposal_decision_batches_proposal_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    idempotency_key_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    decided_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExternalResearchRun(Base):
    """Bookkeeping for externally executed research with a frozen exact context."""

    __tablename__ = "external_research_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["credential_id", "sponsor_user_id"],
            [
                "external_agent_credentials.id",
                "external_agent_credentials.sponsor_user_id",
            ],
            name="fk_external_run_credential_binding",
        ),
        UniqueConstraint(
            "id",
            "credential_id",
            "project_id",
            "sponsor_user_id",
            name="uq_external_research_run_identity",
        ),
        UniqueConstraint(
            "credential_id", "client_request_id", name="uq_external_run_client_request"
        ),
        CheckConstraint(
            "status IN ('OPEN','COMPLETED','FAILED','REVOKED')",
            name="ck_external_research_run_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("external_agent_credentials.id"), index=True
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    client_request_id: Mapped[UUID] = mapped_column()
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    input_revision_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlExternalRunInvocation(Base):
    """Idempotent external operation audit without request bodies or secrets."""

    __tablename__ = "external_run_invocations"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_digest", name="uq_external_invocation_key"),
        CheckConstraint("length(idempotency_digest) = 64", name="ck_external_invocation_key"),
        CheckConstraint("length(request_digest) = 64", name="ck_external_invocation_request"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("external_research_runs.id"), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    idempotency_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    output_type: Mapped[str] = mapped_column(String(64))
    output_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlPlatformAgentVersion",
    "SqlAgentSession",
    "SqlAgentMessage",
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
    "SqlRunWriteGrant",
    "SqlRunRevisionOutput",
    "SqlRunArtifactOutput",
    "SqlRunToolCapability",
    "SqlProposal",
    "SqlProposalChange",
    "SqlProposalChangeDecision",
    "SqlProposalDecisionBatch",
    "SqlExternalResearchRun",
    "SqlExternalRunInvocation",
]


class SqlHostedExecutor(Base):
    """Short-lived host advertisement, separate from attempt leases."""

    __tablename__ = "hosted_executors"
    __table_args__ = (
        CheckConstraint("capacity BETWEEN 0 AND 64", name="hosted_executors_capacity_check"),
    )
    incarnation: Mapped[str] = mapped_column(String(36), default="legacy")
    protocol_version: Mapped[int] = mapped_column(Integer, default=3)
    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    image_digest: Mapped[str] = mapped_column(String(64))
    capacity: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SqlHostedRunArtifact(Base):
    """Private session exports; unlike verification outputs, these assert no evidence."""

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

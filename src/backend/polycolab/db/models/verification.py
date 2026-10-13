"""SQLAlchemy entities owned by the verification capability."""

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
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    ExecutionTenantKind,
    ExecutionWorkloadClass,
    VerificationAttemptState,
    VerificationInputRole,
    VerificationJobState,
    VerificationLanguage,
    VerificationOutputRole,
    VerificationReservationState,
)
from polycolab.entities.time import utc_now


class SqlVerificationEnvironment(Base):
    """Immutable curated runtime identity with separately controlled availability."""

    __tablename__ = "verification_environments"
    __table_args__ = (
        CheckConstraint(
            "language IN ('PYTHON','LEAN')", name="ck_verification_environment_language"
        ),
        CheckConstraint(
            "length(image_digest) = 64", name="ck_verification_environment_image_digest"
        ),
        CheckConstraint(
            "length(dependency_lock_digest) = 64",
            name="ck_verification_environment_dependency_digest",
        ),
        CheckConstraint(
            "length(build_digest) = 64", name="ck_verification_environment_build_digest"
        ),
        CheckConstraint("max_cpu_count >= 1", name="ck_verification_environment_cpu_count"),
        CheckConstraint("max_cpu_seconds >= 1", name="ck_verification_environment_cpu_seconds"),
        CheckConstraint("max_wall_seconds >= 1", name="ck_verification_environment_wall_seconds"),
        CheckConstraint("max_memory_bytes >= 1", name="ck_verification_environment_memory"),
        CheckConstraint("max_process_count >= 1", name="ck_verification_environment_processes"),
        CheckConstraint("max_disk_bytes >= 1", name="ck_verification_environment_disk"),
        CheckConstraint("max_output_bytes >= 0", name="ck_verification_environment_output"),
        CheckConstraint("max_log_bytes >= 0", name="ck_verification_environment_log"),
        CheckConstraint("max_output_files >= 0", name="ck_verification_environment_files"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    language: Mapped[VerificationLanguage] = mapped_column(
        Enum(VerificationLanguage, native_enum=False, length=16)
    )
    image_digest: Mapped[str] = mapped_column(String(64), unique=True)
    toolchain_version: Mapped[str] = mapped_column(String(200))
    dependency_lock_digest: Mapped[str] = mapped_column(String(64))
    build_digest: Mapped[str] = mapped_column(String(64))
    platform_identity: Mapped[str] = mapped_column(String(200))
    max_cpu_count: Mapped[int] = mapped_column(Integer)
    max_cpu_seconds: Mapped[int] = mapped_column(Integer)
    max_wall_seconds: Mapped[int] = mapped_column(Integer)
    max_memory_bytes: Mapped[int] = mapped_column(BigInteger)
    max_process_count: Mapped[int] = mapped_column(Integer)
    max_disk_bytes: Mapped[int] = mapped_column(BigInteger)
    max_output_bytes: Mapped[int] = mapped_column(BigInteger)
    max_log_bytes: Mapped[int] = mapped_column(BigInteger)
    max_output_files: Mapped[int] = mapped_column(Integer)
    available: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    availability_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class SqlVerificationJob(Base):
    """Authorized immutable verification request plus fenced lifecycle state."""

    __tablename__ = "verification_jobs"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('LEAN_CHECK','PYTHON_RUN','CERTIFICATE_GENERATION',"
            "'CERTIFICATE_VERIFICATION')",
            name="ck_verification_job_purpose",
        ),
        CheckConstraint(
            "state IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED','TIMED_OUT')",
            name="ck_verification_job_state",
        ),
        CheckConstraint("current_generation >= 0", name="ck_verification_job_generation"),
        CheckConstraint("event_sequence >= 0", name="ck_verification_job_event_sequence"),
        CheckConstraint("max_attempts >= 1", name="ck_verification_job_max_attempts"),
        CheckConstraint("cpu_count >= 1", name="ck_verification_job_cpu_count"),
        CheckConstraint("cpu_seconds >= 1", name="ck_verification_job_cpu_seconds"),
        CheckConstraint("wall_seconds >= 1", name="ck_verification_job_wall_seconds"),
        CheckConstraint("memory_bytes >= 1", name="ck_verification_job_memory_bytes"),
        CheckConstraint("process_count >= 1", name="ck_verification_job_process_count"),
        CheckConstraint("disk_bytes >= 1", name="ck_verification_job_disk_bytes"),
        CheckConstraint("output_bytes >= 0", name="ck_verification_job_output_bytes"),
        CheckConstraint("log_bytes >= 0", name="ck_verification_job_log_bytes"),
        CheckConstraint("output_files >= 0", name="ck_verification_job_output_files"),
        CheckConstraint("length(manifest_digest) = 64", name="ck_verification_job_manifest_digest"),
        CheckConstraint("length(request_digest) = 64", name="ck_verification_job_request_digest"),
        CheckConstraint("length(retry_key_digest) = 64", name="ck_verification_job_retry_digest"),
        CheckConstraint("contract_version >= 1", name="ck_verification_job_contract_version"),
        UniqueConstraint(
            "sponsor_user_id",
            "ownership_scope_id",
            "retry_key_digest",
            name="uq_verification_job_retry_scope",
        ),
        CheckConstraint(
            "(state IN ('QUEUED','RUNNING') AND terminal_at IS NULL) OR "
            "(state IN ('COMPLETED','FAILED','CANCELLED','TIMED_OUT') AND terminal_at IS NOT NULL)",
            name="ck_verification_job_terminal_time",
        ),
        Index("ix_verification_jobs_queue", "state", "queued_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    work_target_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_revisions.id"), index=True
    )
    research_attempt_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_attempt_revisions.revision_id"), nullable=True, index=True
    )
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("verification_environments.id"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(32))
    evidence_scope: Mapped[str] = mapped_column(String(4000))
    entrypoint: Mapped[str] = mapped_column(String(240))
    arguments: Mapped[list[str]] = mapped_column(JSON)
    seed: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    retry_key_digest: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[int] = mapped_column(Integer, default=1)
    cpu_count: Mapped[int] = mapped_column(Integer)
    cpu_seconds: Mapped[int] = mapped_column(Integer)
    wall_seconds: Mapped[int] = mapped_column(Integer)
    memory_bytes: Mapped[int] = mapped_column(BigInteger)
    process_count: Mapped[int] = mapped_column(Integer)
    disk_bytes: Mapped[int] = mapped_column(BigInteger)
    output_bytes: Mapped[int] = mapped_column(BigInteger)
    log_bytes: Mapped[int] = mapped_column(BigInteger)
    output_files: Mapped[int] = mapped_column(Integer)
    state: Mapped[VerificationJobState] = mapped_column(
        Enum(VerificationJobState, native_enum=False, length=16),
        default=VerificationJobState.QUEUED,
    )
    current_generation: Mapped[int] = mapped_column(Integer, default=0)
    event_sequence: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SqlVerificationInput(Base):
    __tablename__ = "verification_inputs"
    __table_args__ = (
        CheckConstraint(
            "(revision_id IS NOT NULL AND artifact_id IS NULL) OR "
            "(revision_id IS NULL AND artifact_id IS NOT NULL)",
            name="ck_verification_input_identity",
        ),
        CheckConstraint(
            "role IN ('SOURCE','INPUT','CERTIFICATE')", name="ck_verification_input_role"
        ),
        CheckConstraint("position >= 0", name="ck_verification_input_position"),
        CheckConstraint("length(sha256) = 64", name="ck_verification_input_digest"),
        UniqueConstraint("job_id", "path", name="uq_verification_input_path"),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String(240))
    role: Mapped[VerificationInputRole] = mapped_column(
        Enum(VerificationInputRole, native_enum=False, length=16)
    )
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True, index=True
    )
    artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("artifacts.id"), nullable=True, index=True
    )
    sha256: Mapped[str] = mapped_column(String(64))


class SqlVerificationReservation(Base):
    __tablename__ = "verification_reservations"
    __table_args__ = (
        CheckConstraint("state IN ('ACTIVE','RELEASED')", name="ck_verification_reservation_state"),
        CheckConstraint("cpu_seconds >= 1", name="ck_verification_reservation_cpu"),
        CheckConstraint("memory_byte_seconds >= 1", name="ck_verification_reservation_memory"),
        CheckConstraint("disk_bytes >= 1", name="ck_verification_reservation_disk"),
        CheckConstraint("output_bytes >= 0", name="ck_verification_reservation_output"),
        CheckConstraint(
            "(state = 'ACTIVE' AND released_at IS NULL AND accounted_at IS NULL) OR "
            "(state = 'RELEASED' AND released_at IS NOT NULL)",
            name="ck_verification_reservation_release",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), primary_key=True)
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    cpu_seconds: Mapped[int] = mapped_column(BigInteger)
    memory_byte_seconds: Mapped[int] = mapped_column(BigInteger)
    disk_bytes: Mapped[int] = mapped_column(BigInteger)
    output_bytes: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[VerificationReservationState] = mapped_column(
        Enum(VerificationReservationState, native_enum=False, length=16),
        default=VerificationReservationState.ACTIVE,
    )
    admitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accounted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlVerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="ck_verification_attempt_generation"),
        CheckConstraint(
            "state IN ('ACTIVE','COMPLETED','FAILED','CANCELLED','TIMED_OUT','LEASE_LOST')",
            name="ck_verification_attempt_state",
        ),
        CheckConstraint(
            "(state = 'ACTIVE' AND terminal_at IS NULL) OR "
            "(state <> 'ACTIVE' AND terminal_at IS NOT NULL)",
            name="ck_verification_attempt_terminal_time",
        ),
        UniqueConstraint("job_id", "generation", name="uq_verification_attempt_generation"),
        UniqueConstraint("id", "job_id", name="uq_verification_attempt_id_job"),
        Index("ix_verification_attempts_lease", "state", "lease_expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    controller_id: Mapped[str] = mapped_column(String(200))
    state: Mapped[VerificationAttemptState] = mapped_column(
        Enum(VerificationAttemptState, native_enum=False, length=16),
        default=VerificationAttemptState.ACTIVE,
    )
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlExecutionWorkItem(Base):
    """Immutable scheduler input derived only from canonical admitted work."""

    __tablename__ = "execution_work_items"
    __table_args__ = (
        CheckConstraint(
            "(agent_run_id IS NOT NULL AND verification_job_id IS NULL) OR "
            "(agent_run_id IS NULL AND verification_job_id IS NOT NULL)",
            name="ck_execution_work_item_identity",
        ),
        CheckConstraint(
            "workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')",
            name="ck_execution_work_item_class",
        ),
        CheckConstraint("policy_version >= 1", name="ck_execution_work_item_policy"),
        CheckConstraint("reserved_cost >= 1", name="ck_execution_work_item_cost"),
        CheckConstraint("wall_seconds >= 1", name="ck_execution_work_item_wall"),
        CheckConstraint(
            "((workload_class = 'AGENT' AND agent_run_id IS NOT NULL "
            "AND agent_model_tokens IS NOT NULL AND agent_provider_cost_microusd IS NOT NULL "
            "AND verification_cpu_seconds IS NULL "
            "AND verification_memory_byte_seconds IS NULL) OR "
            "(workload_class <> 'AGENT' AND verification_job_id IS NOT NULL "
            "AND agent_model_tokens IS NULL AND agent_provider_cost_microusd IS NULL "
            "AND verification_cpu_seconds IS NOT NULL "
            "AND verification_memory_byte_seconds IS NOT NULL))",
            name="ck_execution_work_item_resource_shape",
        ),
        CheckConstraint(
            "agent_model_tokens IS NULL OR agent_model_tokens >= 1",
            name="ck_execution_work_item_agent_tokens",
        ),
        CheckConstraint(
            "agent_provider_cost_microusd IS NULL OR agent_provider_cost_microusd >= 1",
            name="ck_execution_work_item_agent_cost",
        ),
        CheckConstraint(
            "verification_cpu_seconds IS NULL OR verification_cpu_seconds >= 1",
            name="ck_execution_work_item_verification_cpu",
        ),
        CheckConstraint(
            "verification_memory_byte_seconds IS NULL OR verification_memory_byte_seconds >= 1",
            name="ck_execution_work_item_verification_memory",
        ),
        Index("ix_execution_work_items_queue", "workload_class", "queued_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True, unique=True
    )
    verification_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verification_jobs.id"), nullable=True, unique=True
    )
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    workload_class: Mapped[ExecutionWorkloadClass] = mapped_column(
        Enum(ExecutionWorkloadClass, native_enum=False, length=24)
    )
    policy_version: Mapped[int] = mapped_column(Integer)
    reserved_cost: Mapped[int] = mapped_column(BigInteger)
    agent_model_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    agent_provider_cost_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verification_cpu_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    verification_memory_byte_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wall_seconds: Mapped[int] = mapped_column(BigInteger)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExecutionClassState(Base):
    """Durable class floor; never deleted or moved backward."""

    __tablename__ = "execution_class_states"
    __table_args__ = (
        CheckConstraint(
            "workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')",
            name="ck_execution_class_name",
        ),
        CheckConstraint("active_policy_version >= 1", name="ck_execution_class_policy"),
        CheckConstraint("virtual_runtime_floor >= 0", name="ck_execution_class_floor"),
        CheckConstraint("scheduling_sequence >= 0", name="ck_execution_class_sequence"),
    )
    workload_class: Mapped[ExecutionWorkloadClass] = mapped_column(
        Enum(ExecutionWorkloadClass, native_enum=False, length=24), primary_key=True
    )
    active_policy_version: Mapped[int] = mapped_column(Integer)
    virtual_runtime_floor: Mapped[int] = mapped_column(BigInteger, default=0)
    scheduling_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlExecutionFairnessState(Base):
    """Private equal-weight hierarchical virtual runtime for one tenant."""

    __tablename__ = "execution_fairness_states"
    __table_args__ = (
        CheckConstraint("tenant_kind IN ('USER','PROJECT')", name="ck_execution_tenant_kind"),
        CheckConstraint("policy_version >= 1", name="ck_execution_fairness_policy"),
        CheckConstraint("virtual_runtime >= 0", name="ck_execution_fairness_runtime"),
    )
    workload_class: Mapped[ExecutionWorkloadClass] = mapped_column(
        ForeignKey("execution_class_states.workload_class"), primary_key=True
    )
    tenant_kind: Mapped[ExecutionTenantKind] = mapped_column(
        Enum(ExecutionTenantKind, native_enum=False, length=16), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    virtual_runtime: Mapped[int] = mapped_column(BigInteger)
    last_served_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlExecutionSlotLease(Base):
    """Fenced logical lease whose physical occupancy has a separate safe bound."""

    __tablename__ = "execution_slot_leases"
    __table_args__ = (
        CheckConstraint(
            "workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')",
            name="ck_execution_slot_class",
        ),
        CheckConstraint("generation >= 1", name="ck_execution_slot_generation"),
        CheckConstraint(
            "(agent_run_id IS NOT NULL AND verification_attempt_id IS NULL) OR "
            "(agent_run_id IS NULL AND verification_attempt_id IS NOT NULL)",
            name="ck_execution_slot_identity",
        ),
        CheckConstraint("lease_expires_at >= acquired_at", name="ck_execution_slot_lease_time"),
        CheckConstraint("lease_expires_at <= safe_release_at", name="ck_execution_slot_safe_bound"),
        CheckConstraint(
            "termination_confirmed_at IS NULL OR termination_confirmed_at >= acquired_at",
            name="ck_execution_slot_termination_time",
        ),
        CheckConstraint(
            "released_at IS NULL OR released_at >= acquired_at",
            name="ck_execution_slot_release_time",
        ),
        CheckConstraint(
            "released_at IS NULL OR termination_confirmed_at IS NOT NULL "
            "OR released_at >= safe_release_at",
            name="ck_execution_slot_release_safety",
        ),
        CheckConstraint(
            "released_at IS NULL OR termination_confirmed_at IS NULL "
            "OR released_at >= termination_confirmed_at",
            name="ck_execution_slot_release_after_termination",
        ),
        UniqueConstraint("agent_run_id", "generation", name="uq_execution_slot_agent_attempt"),
        Index(
            "ix_execution_slot_capacity",
            "workload_class",
            "released_at",
            "safe_release_at",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    work_item_id: Mapped[UUID] = mapped_column(ForeignKey("execution_work_items.id"), index=True)
    workload_class: Mapped[ExecutionWorkloadClass] = mapped_column(
        Enum(ExecutionWorkloadClass, native_enum=False, length=24)
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    verification_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verification_attempts.id"), nullable=True, unique=True
    )
    generation: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[str] = mapped_column(String(200))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    safe_release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    termination_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlVerificationEvent(Base):
    __tablename__ = "verification_events"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_verification_event_sequence"),
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            ["verification_attempts.id", "verification_attempts.job_id"],
            name="fk_verification_event_attempt_job",
        ),
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), primary_key=True)
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    attempt_id: Mapped[UUID | None] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlVerificationResult(Base):
    __tablename__ = "verification_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            ["verification_attempts.id", "verification_attempts.job_id"],
            name="fk_verification_result_attempt_job",
        ),
        CheckConstraint(
            "outcome IN ('COMPLETED','FAILED','CANCELLED','TIMED_OUT')",
            name="ck_verification_result_outcome",
        ),
        CheckConstraint(
            "length(completion_request_digest) = 64",
            name="ck_verification_result_completion_digest",
        ),
        CheckConstraint(
            "length(input_manifest_digest) = 64",
            name="ck_verification_result_manifest_digest",
        ),
        UniqueConstraint("id", "attempt_id", "job_id", name="uq_verification_result_binding"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), index=True)
    attempt_id: Mapped[UUID] = mapped_column(unique=True)
    environment_id: Mapped[UUID] = mapped_column(ForeignKey("verification_environments.id"))
    input_manifest_digest: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16))
    diagnostic_summary: Mapped[dict[str, object]] = mapped_column(JSON)
    usage_summary: Mapped[dict[str, object]] = mapped_column(JSON)
    completion_request_digest: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlVerificationOutputArtifact(Base):
    __tablename__ = "verification_output_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["attempt_id", "job_id"],
            ["verification_attempts.id", "verification_attempts.job_id"],
            name="fk_verification_output_attempt_job",
        ),
        ForeignKeyConstraint(
            ["result_id", "attempt_id", "job_id"],
            [
                "verification_results.id",
                "verification_results.attempt_id",
                "verification_results.job_id",
            ],
            name="fk_verification_output_result_binding",
        ),
        CheckConstraint(
            "role IN ('OUTPUT','CERTIFICATE','DIAGNOSTIC')",
            name="ck_verification_output_role",
        ),
        UniqueConstraint("artifact_id", name="uq_verification_output_artifact"),
        UniqueConstraint("attempt_id", "path", name="uq_verification_output_path"),
    )
    attempt_id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("verification_jobs.id"), index=True)
    result_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("verification_results.id"), nullable=True, index=True
    )
    path: Mapped[str] = mapped_column(String(240))
    role: Mapped[VerificationOutputRole] = mapped_column(
        Enum(VerificationOutputRole, native_enum=False, length=16)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlVerificationEnvironment",
    "SqlVerificationJob",
    "SqlVerificationInput",
    "SqlVerificationReservation",
    "SqlVerificationAttempt",
    "SqlExecutionWorkItem",
    "SqlExecutionClassState",
    "SqlExecutionFairnessState",
    "SqlExecutionSlotLease",
    "SqlVerificationEvent",
    "SqlVerificationResult",
    "SqlVerificationOutputArtifact",
]

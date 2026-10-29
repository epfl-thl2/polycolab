"""SQLAlchemy entities owned by the execution capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
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
)
from polycolab.entities.time import utc_now


class SqlExecutionWorkItem(Base):
    """Immutable scheduler input derived only from canonical admitted work."""

    __tablename__ = "execution_work_items"
    __table_args__ = (
        CheckConstraint(
            "workload_class = 'AGENT'",
            name="ck_execution_work_item_class",
        ),
        CheckConstraint("policy_version >= 1", name="ck_execution_work_item_policy"),
        CheckConstraint("reserved_cost >= 1", name="ck_execution_work_item_cost"),
        CheckConstraint("wall_seconds >= 1", name="ck_execution_work_item_wall"),
        CheckConstraint(
            "agent_model_tokens IS NULL OR agent_model_tokens >= 1",
            name="ck_execution_work_item_agent_tokens",
        ),
        CheckConstraint(
            "agent_provider_cost_microusd IS NULL OR agent_provider_cost_microusd >= 1",
            name="ck_execution_work_item_agent_cost",
        ),
        Index("ix_execution_work_items_queue", "workload_class", "queued_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True, unique=True
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
    wall_seconds: Mapped[int] = mapped_column(BigInteger)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExecutionClassState(Base):
    """Durable class floor; never deleted or moved backward."""

    __tablename__ = "execution_class_states"
    __table_args__ = (
        CheckConstraint(
            "workload_class = 'AGENT'",
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
            "workload_class = 'AGENT'",
            name="ck_execution_slot_class",
        ),
        CheckConstraint("generation >= 1", name="ck_execution_slot_generation"),
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
    generation: Mapped[int] = mapped_column(Integer)
    owner_id: Mapped[str] = mapped_column(String(200))
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    safe_release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    termination_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

"""Durable hosted-agent fairness and physical capacity, owned by the API.

No provider or runtime operations take place in these transactions. Verification
pools remain disabled. All allocation writers serialize after tenant scope locks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session, aliased

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentSession,
    SqlExecutionClassState,
    SqlExecutionFairnessState,
    SqlExecutionSlotLease,
    SqlExecutionWorkItem,
    SqlHostedExecutor,
    SqlHostedSlot,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    AgentRunStatus,
    AgentSessionStatus,
    ExecutionTenantKind,
    ExecutionWorkloadClass,
)
from polycolab.entities.time import utc_now
from polycolab.execution.limits import _lock_scopes
from polycolab.execution.scheduling import AgentCostPolicy, advance_runtime, reserved_agent_cost

AGENT = ExecutionWorkloadClass.AGENT
POLICY = AgentCostPolicy(1, 100_000, 1_000_000, 60)
TERMINAL = (
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.TIMED_OUT,
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def admit(session: Session, run: SqlAgentRun) -> None:
    """Attach the exact finite work item before the admission transaction commits."""
    if run.runtime_spec is None:
        return
    spec = RuntimeSpec.model_validate(run.runtime_spec)
    if run.deadline_at is None:
        raise ValueError("hosted run requires an absolute deadline")
    session.flush()
    tokens = spec.max_model_requests * (spec.max_input_tokens + spec.max_output_tokens)
    cost = max(1, spec.max_model_requests * spec.round_cost_microusd)
    session.add(
        SqlExecutionWorkItem(
            agent_run_id=run.id,
            sponsor_user_id=run.requested_by_user_id,
            project_id=run.project_id,
            workload_class=AGENT,
            policy_version=POLICY.version,
            reserved_cost=reserved_agent_cost(
                model_tokens=tokens,
                provider_cost_microusd=cost,
                wall_seconds=spec.limits.wall_seconds,
                policy=POLICY,
            ),
            agent_model_tokens=tokens,
            agent_provider_cost_microusd=cost,
            wall_seconds=spec.limits.wall_seconds,
            queued_at=run.created_at,
        )
    )
    session.flush()


def _serialize(session: Session) -> SqlExecutionClassState:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(704321009)"))
    row = session.scalar(
        select(SqlExecutionClassState)
        .where(SqlExecutionClassState.workload_class == AGENT)
        .with_for_update()
    )
    if row is None:
        row = SqlExecutionClassState(
            workload_class=AGENT,
            active_policy_version=1,
            virtual_runtime_floor=0,
            scheduling_sequence=0,
        )
        session.add(row)
        session.flush()
    if row.active_policy_version != POLICY.version:
        raise ValueError("scheduler policy requires a drained transition")
    return row


def _candidate(
    session: Session,
    now: datetime,
    tenant_capacity: int,
    project_capacity: int,
    sandbox_backend: str = "microsandbox",
    sandbox_version: str = "0.6.18",
    image_digest: str | None = None,
) -> SqlAgentRun | None:
    user = aliased(SqlExecutionFairnessState)
    project = aliased(SqlExecutionFairnessState)
    previous = aliased(SqlAgentRun)
    occupied = (
        select(SqlExecutionSlotLease.id)
        .where(
            SqlExecutionSlotLease.agent_run_id == SqlAgentRun.id,
            SqlExecutionSlotLease.released_at.is_(None),
            (
                (SqlExecutionSlotLease.safe_release_at > now)
                | exists(
                    select(SqlHostedSlot.ordinal).where(
                        SqlHostedSlot.run_id == SqlExecutionSlotLease.agent_run_id,
                        SqlHostedSlot.generation == SqlExecutionSlotLease.generation,
                        SqlHostedSlot.quarantined.is_(True),
                    )
                )
            ),
        )
        .correlate(SqlAgentRun)
        .exists()
    )

    def count_scope(user_scope: bool):  # type: ignore[no-untyped-def]
        item = aliased(SqlExecutionWorkItem)
        return (
            select(func.count())
            .select_from(SqlExecutionSlotLease)
            .join(item, item.id == SqlExecutionSlotLease.work_item_id)
            .where(
                SqlExecutionSlotLease.workload_class == AGENT,
                SqlExecutionSlotLease.released_at.is_(None),
                (
                    (SqlExecutionSlotLease.safe_release_at > now)
                    | exists(
                        select(SqlHostedSlot.ordinal).where(
                            SqlHostedSlot.run_id == SqlExecutionSlotLease.agent_run_id,
                            SqlHostedSlot.generation == SqlExecutionSlotLease.generation,
                            SqlHostedSlot.quarantined.is_(True),
                        )
                    )
                ),
                item.sponsor_user_id == SqlAgentRun.requested_by_user_id
                if user_scope
                else item.project_id == SqlAgentRun.project_id,
            )
            .correlate(SqlAgentRun)
            .scalar_subquery()
        )

    floor = (
        session.scalar(
            select(SqlExecutionClassState.virtual_runtime_floor).where(
                SqlExecutionClassState.workload_class == AGENT
            )
        )
        or 0
    )
    score = func.greatest(
        floor,
        func.coalesce(user.virtual_runtime, floor),
        func.coalesce(project.virtual_runtime, floor),
    )
    return session.scalar(
        select(SqlAgentRun)
        .join(SqlExecutionWorkItem, SqlExecutionWorkItem.agent_run_id == SqlAgentRun.id)
        .join(SqlAgentSession, SqlAgentSession.id == SqlAgentRun.session_id)
        .outerjoin(
            user,
            (user.workload_class == AGENT)
            & (user.tenant_kind == ExecutionTenantKind.USER)
            & (user.tenant_id == SqlAgentRun.requested_by_user_id),
        )
        .outerjoin(
            project,
            (project.workload_class == AGENT)
            & (project.tenant_kind == ExecutionTenantKind.PROJECT)
            & (project.tenant_id == SqlAgentRun.project_id),
        )
        .where(
            func.coalesce(SqlAgentRun.runtime_spec["sandbox_backend"].as_string(), "microsandbox")
            == sandbox_backend,
            func.coalesce(SqlAgentRun.runtime_spec["sandbox_version"].as_string(), "0.6.18")
            == sandbox_version,
            *(
                [SqlAgentRun.runtime_spec["image"].as_string().endswith("@sha256:" + image_digest)]
                if image_digest is not None
                else []
            ),
            SqlAgentRun.status == AgentRunStatus.QUEUED,
            SqlAgentSession.status == AgentSessionStatus.ACTIVE,
            SqlExecutionWorkItem.policy_version == POLICY.version,
            ~occupied,
            count_scope(True) < tenant_capacity,
            count_scope(False) < project_capacity,
            ~exists(
                select(previous.id).where(
                    previous.session_id == SqlAgentRun.session_id,
                    previous.queue_sequence < SqlAgentRun.queue_sequence,
                    previous.status.not_in(TERMINAL),
                )
            ),
        )
        .order_by(score, SqlAgentRun.created_at, SqlAgentRun.id)
        .limit(1)
    )


def claim(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    capacity: int,
    user_capacity: int,
    project_capacity: int,
    slot_id: int | None = None,
    incarnation: str | None = None,
    image_digest: str | None = None,
    sandbox_backend: str = "microsandbox",
    sandbox_version: str = "0.6.18",
) -> SqlAgentRun | None:
    from polycolab.agents.sessions import _append_event_locked, claim_next_run_in_transaction
    from polycolab.entities.enums import AgentRunEventKind

    if min(capacity, user_capacity, project_capacity) <= 0:
        return None
    for _ in range(100):
        now = utc_now()
        candidate = _candidate(
            session,
            now,
            user_capacity,
            project_capacity,
            sandbox_backend,
            sandbox_version,
            image_digest,
        )
        if candidate is None:
            session.rollback()
            return None
        run_id, user_id, project_id = (
            candidate.id,
            candidate.requested_by_user_id,
            candidate.project_id,
        )
        session.rollback()
        try:
            _lock_scopes(session, user_id=user_id, project_id=project_id)
            state = _serialize(session)
            if image_digest is not None:
                executor = session.get(SqlHostedExecutor, worker_id)
                if (
                    executor is None
                    or executor.incarnation != incarnation
                    or executor.protocol_version != 5
                    or utc(executor.expires_at) <= utc_now()
                    or executor.image_digest != image_digest
                    or executor.sandbox_backend != sandbox_backend
                    or executor.sandbox_version != sandbox_version
                    or slot_id is None
                ):
                    from polycolab.agents.runtime.errors import RuntimeApiConflict

                    raise RuntimeApiConflict("executor_not_ready")
            host_slot = (
                session.get(SqlHostedSlot, (worker_id, slot_id)) if slot_id is not None else None
            )
            if slot_id is not None and (
                host_slot is None or host_slot.quarantined or host_slot.run_id is not None
            ):
                session.rollback()
                return None
            candidate = _candidate(
                session,
                now,
                user_capacity,
                project_capacity,
                sandbox_backend,
                sandbox_version,
                image_digest,
            )
            if candidate is None or candidate.id != run_id:
                session.rollback()
                continue
            occupied = (
                session.scalar(
                    select(func.count())
                    .select_from(SqlExecutionSlotLease)
                    .where(
                        SqlExecutionSlotLease.workload_class == AGENT,
                        SqlExecutionSlotLease.released_at.is_(None),
                        (
                            (SqlExecutionSlotLease.safe_release_at > now)
                            | exists(
                                select(SqlHostedSlot.ordinal).where(
                                    SqlHostedSlot.run_id == SqlExecutionSlotLease.agent_run_id,
                                    SqlHostedSlot.generation == SqlExecutionSlotLease.generation,
                                    SqlHostedSlot.quarantined.is_(True),
                                )
                            )
                        ),
                    )
                )
                or 0
            )
            if occupied >= capacity:
                session.rollback()
                return None
            run = session.scalar(
                select(SqlAgentRun).where(SqlAgentRun.id == run_id).with_for_update()
            )
            assert run is not None
            if not project_policy.can(
                SqlAlchemyTransaction(session), project_id, user_id, ProjectAction.RUN_AGENTS
            ):
                run.status = AgentRunStatus.FAILED
                run.failure_code = "authorization_revoked"
                run.finished_at = now
                _append_event_locked(
                    session,
                    run=run,
                    idempotency_key="authorization-before-claim",
                    kind=AgentRunEventKind.RUN_FAILED,
                    payload={"code": run.failure_code},
                    occurred_at=now,
                )
                session.commit()
                continue
            states = []
            for kind, tenant in (
                (ExecutionTenantKind.USER, user_id),
                (ExecutionTenantKind.PROJECT, project_id),
            ):
                row = session.scalar(
                    select(SqlExecutionFairnessState)
                    .where(
                        SqlExecutionFairnessState.workload_class == AGENT,
                        SqlExecutionFairnessState.tenant_kind == kind,
                        SqlExecutionFairnessState.tenant_id == tenant,
                    )
                    .with_for_update()
                )
                if row is None:
                    row = SqlExecutionFairnessState(
                        workload_class=AGENT,
                        tenant_kind=kind,
                        tenant_id=tenant,
                        policy_version=POLICY.version,
                        virtual_runtime=state.virtual_runtime_floor,
                    )
                    session.add(row)
                states.append(row)
            run = claim_next_run_in_transaction(
                session,
                worker_id=worker_id,
                lease_for=timedelta(seconds=lease_seconds),
                now=now,
                engine="codex",
                run_id=run_id,
            )
            if run is None:
                session.commit()
                continue
            item = session.scalar(
                select(SqlExecutionWorkItem).where(SqlExecutionWorkItem.agent_run_id == run_id)
            )
            assert item is not None and run.deadline_at is not None
            floor = max(row.virtual_runtime for row in states)
            for row in states:
                row.virtual_runtime = advance_runtime(
                    max(row.virtual_runtime, state.virtual_runtime_floor), item.reserved_cost
                )
                row.last_served_at = now
            state.virtual_runtime_floor = max(state.virtual_runtime_floor, floor)
            state.scheduling_sequence = advance_runtime(state.scheduling_sequence, 1)
            session.flush()
            session.add(
                SqlExecutionSlotLease(
                    work_item_id=item.id,
                    workload_class=AGENT,
                    agent_run_id=run.id,
                    generation=run.lease_generation,
                    owner_id=worker_id,
                    acquired_at=run.lease_acquired_at,
                    lease_expires_at=run.lease_expires_at,
                    safe_release_at=utc(run.deadline_at) + timedelta(seconds=30),
                )
            )
            if host_slot is not None:
                host_slot.run_id, host_slot.generation = run.id, run.lease_generation
            session.commit()
            session.refresh(run)
            return run
        except Exception:
            session.rollback()
            raise
    return None


def confirm_termination(session: Session, *, run_id: UUID, generation: int, owner: str) -> None:
    """Trusted host evidence can release an old fence, never reopen its run."""
    run = session.get(SqlAgentRun, run_id)
    if run is None:
        raise ValueError("run_not_found")
    _lock_scopes(session, user_id=run.requested_by_user_id, project_id=run.project_id)
    _serialize(session)
    slot = session.scalar(
        select(SqlExecutionSlotLease)
        .where(
            SqlExecutionSlotLease.agent_run_id == run_id,
            SqlExecutionSlotLease.generation == generation,
            SqlExecutionSlotLease.owner_id == owner,
        )
        .with_for_update()
    )
    if slot is None:
        raise ValueError("slot_not_found")
    for host_slot in session.scalars(
        select(SqlHostedSlot)
        .where(
            SqlHostedSlot.worker_id == owner,
            SqlHostedSlot.run_id == run_id,
            SqlHostedSlot.generation == generation,
        )
        .with_for_update()
    ):
        host_slot.run_id = host_slot.generation = None
        host_slot.quarantined = False
    if slot.released_at is None:
        slot.termination_confirmed_at = utc_now()
        slot.released_at = slot.termination_confirmed_at
    session.commit()

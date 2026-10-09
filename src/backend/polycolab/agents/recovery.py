"""Canonical hosted terminal transitions, independent of worker liveness."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.agents.sessions import (
    IdempotencyConflict,
    LeaseLost,
    _append_event_locked,
    _revoke_run_capabilities,
    finish_run,
)
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentSession,
    SqlContributionEnvelope,
    SqlHostedCompletion,
    SqlHostedModelRequest,
)
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus
from polycolab.entities.time import utc_now
from polycolab.execution.allocator import utc
from polycolab.execution.limits import _lock_scopes
from polycolab.platform.observability import increment_durable

TERMINAL = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.FAILED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.TIMED_OUT,
}


def lock_run(session: Session, run_id: UUID) -> SqlAgentRun:
    initial = session.get(SqlAgentRun, run_id)
    if initial is None:
        raise LeaseLost
    _lock_scopes(session, user_id=initial.requested_by_user_id, project_id=initial.project_id)
    session.execute(
        select(SqlAgentSession).where(SqlAgentSession.id == initial.session_id).with_for_update()
    )
    run = session.scalar(
        select(SqlAgentRun)
        .where(SqlAgentRun.id == run_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    assert run is not None
    return run


def effects_possible(session: Session, run_id: UUID) -> bool:
    return any(
        session.scalar(select(exists().where(condition)))
        for condition in (
            SqlHostedModelRequest.run_id == run_id,
            SqlContributionEnvelope.run_id == run_id,
            (SqlAgentRunEvent.run_id == run_id)
            & (SqlAgentRunEvent.kind == AgentRunEventKind.TOOL_REQUESTED),
        )
    )


def reconcile_one(session: Session, run_id: UUID, *, commit: bool = True) -> bool:
    run = lock_run(session, run_id)
    now = utc_now()
    if run.runtime_spec is None or run.status in TERMINAL:
        session.rollback()
        return False
    deadline = run.deadline_at is not None and utc(run.deadline_at) <= now
    expired = run.lease_expires_at is not None and utc(run.lease_expires_at) <= now
    if not deadline and not expired:
        session.rollback()
        return False
    _revoke_run_capabilities(session, run.id)
    if run.status == AgentRunStatus.CANCELLING:
        status, code = AgentRunStatus.CANCELLED, "cancelled_after_runner_loss"
    elif deadline:
        status, code = AgentRunStatus.TIMED_OUT, "deadline_exceeded"
    elif effects_possible(session, run.id):
        status, code = AgentRunStatus.FAILED, "runner_lost_resume_required"
    elif run.attempt >= RuntimeSpec.model_validate(run.runtime_spec).max_attempts:
        status, code = AgentRunStatus.FAILED, "runner_lost"
    else:
        status, code = AgentRunStatus.QUEUED, "retry_before_external_effects"
    run.status = status
    run.lease_owner = run.lease_expires_at = None
    if status in TERMINAL:
        run.finished_at = now
        run.failure_code = code
    kind = {
        AgentRunStatus.CANCELLED: AgentRunEventKind.RUN_CANCELLED,
        AgentRunStatus.TIMED_OUT: AgentRunEventKind.RUN_TIMED_OUT,
        AgentRunStatus.FAILED: AgentRunEventKind.RUN_FAILED,
    }.get(status, AgentRunEventKind.RUNNER_LOST)
    _append_event_locked(
        session,
        run=run,
        idempotency_key=f"hosted-recovery-{run.lease_generation}",
        kind=kind,
        payload={"code": code},
        occurred_at=now,
    )
    increment_durable(session, "polycolab_hosted_recovery_total", outcome=status.value)
    if commit:
        session.commit()
    return True


def reconcile(session: Session, limit: int = 100) -> int:
    ids = list(
        session.scalars(
            select(SqlAgentRun.id)
            .where(
                SqlAgentRun.runtime_spec["engine"].as_string() == "codex",
                SqlAgentRun.status.not_in(TERMINAL),
                or_(
                    SqlAgentRun.deadline_at <= utc_now(), SqlAgentRun.lease_expires_at <= utc_now()
                ),
            )
            .order_by(SqlAgentRun.created_at, SqlAgentRun.id)
            .limit(limit)
        )
    )
    session.rollback()
    return sum(reconcile_one(session, run_id) for run_id in ids)


def complete(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    generation: int,
    status: AgentRunStatus,
    failure_code: str | None,
    final_message_md: str | None,
) -> None:
    digest = hashlib.sha256(
        json.dumps(
            [status.value, failure_code, final_message_md],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    run = lock_run(session, run_id)
    receipt = session.get(SqlHostedCompletion, (run_id, generation))
    if receipt is not None:
        if receipt.worker_id != worker_id or receipt.payload_digest != digest:
            raise IdempotencyConflict
        session.rollback()
        return
    if run.lease_generation != generation or run.lease_owner != worker_id:
        raise LeaseLost
    if run.deadline_at is not None and utc(run.deadline_at) <= utc_now():
        reconcile_one(session, run_id, commit=False)
        if status != run.status:
            session.commit()
            raise LeaseLost
        session.add(
            SqlHostedCompletion(
                run_id=run_id, generation=generation, worker_id=worker_id, payload_digest=digest
            )
        )
        session.commit()
        return
    session.add(
        SqlHostedCompletion(
            run_id=run_id, generation=generation, worker_id=worker_id, payload_digest=digest
        )
    )
    finish_run(
        session,
        run_id=run_id,
        worker_id=worker_id,
        lease_generation=generation,
        status=status,
        failure_code=failure_code,
        final_message_md=final_message_md,
    )

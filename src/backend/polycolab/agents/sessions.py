"""Transactional canonical session/run state for the WP-09 built-in worker.

This module deliberately knows nothing about HTTP, providers, research context,
tools, or proposals. It owns ordered product history and lease-safe state only.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session, aliased

from polycolab.agents import grants as run_grants
from polycolab.agents.schemas import RunAuthorityRequest
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentRunUsage,
    SqlAgentSession,
    SqlGatewayProfile,
    SqlPlatformAgentVersion,
    SqlRuntimeRunBinding,
    SqlRuntimeSessionBinding,
    SqlRunToolCapability,
)
from polycolab.db.models.project_tasks import SqlProjectTask
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    AgentSessionStatus,
    ExecutionProfile,
    PlatformAgentKind,
    RuntimeBindingStatus,
    UsageSource,
)
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.execution.limits import ExecutionLimits, enforce_execution_limits
from polycolab.platform.observability import increment_durable, metrics, observe_durable


class SessionStateError(Exception):
    """A session/run transition would violate canonical lifecycle state."""


class SessionNotFound(Exception):
    """Raised by the domain layer; HTTP authorization decides disclosure."""


class LeaseLost(SessionStateError):
    """An event or transition came from a worker whose lease is no longer valid."""


class IdempotencyConflict(SessionStateError):
    """An idempotency key was reused for a different immutable operation."""


RESEARCHER_VERSION_ID = UUID("a0000000-0000-4000-8000-000000000001")
CRITIC_VERSION_ID = UUID("a0000000-0000-4000-8000-000000000002")

_PLATFORM_V1: tuple[tuple[UUID, PlatformAgentKind, str, str], ...] = (
    (
        RESEARCHER_VERSION_ID,
        PlatformAgentKind.RESEARCHER,
        "Researcher",
        "Explore mathematical claims and decompose problems.",
    ),
    (
        CRITIC_VERSION_ID,
        PlatformAgentKind.CRITIC,
        "Critic",
        "Find gaps, hidden assumptions, and counterexamples.",
    ),
)
_PLATFORM_V2: tuple[tuple[UUID, PlatformAgentKind, str, str], ...] = (
    (
        UUID("a0000000-0000-4000-8000-000000000003"),
        PlatformAgentKind.RESEARCHER,
        "Researcher",
        "Explore mathematical claims. Save scoped research directly only when granted; "
        "suggest edits outside authority. Persistence is not verification or endorsement.",
    ),
    (
        UUID("a0000000-0000-4000-8000-000000000004"),
        PlatformAgentKind.CRITIC,
        "Critic",
        "Find gaps and counterexamples. Retain failed attempts with explanations. "
        "Use scoped writes only when granted; suggest unauthorized edits. "
        "Never claim verification.",
    ),
)
_TERMINAL = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.FAILED,
        AgentRunStatus.TIMED_OUT,
    }
)
_LEASED = frozenset({AgentRunStatus.CLAIMED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING})
_WORKER_EVENT_KINDS = frozenset(
    {
        AgentRunEventKind.ASSISTANT_DELTA,
        AgentRunEventKind.TOOL_REQUESTED,
        AgentRunEventKind.TOOL_RESULT,
    }
)


def _revoke_run_capabilities(session: Session, run_id: UUID) -> None:
    """Terminal, archival, and recovery paths invalidate opaque run grants."""

    session.execute(
        update(SqlRunToolCapability)
        .where(SqlRunToolCapability.run_id == run_id, SqlRunToolCapability.revoked.is_(False))
        .values(revoked=True)
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def ensure_platform_agent_versions(session: Session) -> None:
    """Seed the immutable v1 specs for metadata-created local/test databases."""

    changed = False
    for version_id, kind, display_name, instructions in (*_PLATFORM_V1, *_PLATFORM_V2):
        existing = session.get(SqlPlatformAgentVersion, version_id)
        if existing is None:
            session.add(
                SqlPlatformAgentVersion(
                    id=version_id,
                    agent_kind=kind,
                    version=1 if version_id in {item[0] for item in _PLATFORM_V1} else 2,
                    display_name=display_name,
                    instructions_text=instructions,
                    instructions_digest=sha256(instructions.encode()).hexdigest(),
                    execution_profile=ExecutionProfile.TRUSTED_HOSTED,
                )
            )
            changed = True
    if changed:
        _commit(session)


def platform_agent_version(
    session: Session, *, agent_kind: PlatformAgentKind, version: int = 1
) -> SqlPlatformAgentVersion:
    ensure_platform_agent_versions(session)
    agent_version = session.scalar(
        select(SqlPlatformAgentVersion).where(
            SqlPlatformAgentVersion.agent_kind == agent_kind,
            SqlPlatformAgentVersion.version == version,
            SqlPlatformAgentVersion.execution_profile == ExecutionProfile.TRUSTED_HOSTED,
        )
    )
    if agent_version is None:
        raise SessionNotFound
    return agent_version


def create_agent_session(
    session: Session,
    *,
    project_id: UUID,
    created_by_user_id: UUID,
    agent_kind: PlatformAgentKind,
    title: str | None = None,
    version: int = 1,
    harness: Literal["codex"] | None = None,
    system_prompt: str | None = None,
    task_id: UUID | None = None,
) -> SqlAgentSession:
    """Create a shared project session pinned to a platform v1 agent definition."""

    if task_id is None:
        task_id = session.scalar(
            select(SqlProjectTask.id).where(
                SqlProjectTask.project_id == project_id, SqlProjectTask.branch == "main"
            )
        )
    if task_id is not None:
        task = session.scalar(
            select(SqlProjectTask)
            .where(SqlProjectTask.id == task_id, SqlProjectTask.project_id == project_id)
            .with_for_update()
        )
        if task is None:
            raise RepositoryError("project_task_not_found", 404)
        if task.archived_at is not None:
            raise RepositoryError("task_archived")
    agent_version = platform_agent_version(session, agent_kind=agent_kind, version=version)
    result = SqlAgentSession(
        task_id=task_id,
        project_id=project_id,
        agent_version_id=agent_version.id,
        created_by_user_id=created_by_user_id,
        title=title,
        harness=harness,
        system_prompt=system_prompt,
    )
    session.add(result)
    _commit(session)
    session.refresh(result)
    return result


def _locked_session(session: Session, session_id: UUID) -> SqlAgentSession:
    task_id = session.scalar(
        select(SqlAgentSession.task_id).where(SqlAgentSession.id == session_id)
    )
    if task_id is not None:
        session.scalar(
            select(SqlProjectTask)
            .where(SqlProjectTask.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    result = session.scalar(
        select(SqlAgentSession)
        .where(SqlAgentSession.id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise SessionNotFound
    return result


def _active_profile(session: Session, *, profile_id: UUID, user_id: UUID) -> SqlGatewayProfile:
    profile = session.scalar(
        select(SqlGatewayProfile)
        .where(
            SqlGatewayProfile.id == profile_id,
            SqlGatewayProfile.user_id == user_id,
            SqlGatewayProfile.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if profile is None:
        raise SessionStateError("gateway profile is unavailable")
    return profile


def append_user_message_and_queue_run(
    session: Session,
    *,
    session_id: UUID,
    requested_by_user_id: UUID,
    gateway_profile_id: UUID,
    content_md: str,
    context_revision_ids: list[UUID] | None = None,
    context_artifact_ids: list[UUID] | None = None,
    client_request_id: UUID | None = None,
    deadline_at: datetime | None = None,
    execution_limits: ExecutionLimits | None = None,
    now: datetime | None = None,
    requested_authority: RunAuthorityRequest | None = None,
    runtime_spec: dict[str, object] | None = None,
) -> tuple[SqlAgentMessage, SqlAgentRun]:
    """Append a human message and its ordered run atomically.

    The requester-owned profile's model and credential version are copied to the
    durable run; no secret or run grant is persisted.
    """

    if not content_md.strip():
        raise SessionStateError("message must not be empty")
    parent = _locked_session(session, session_id)
    if parent.status is not AgentSessionStatus.ACTIVE:
        raise SessionStateError("session is archived")
    if parent.task_id is not None:
        task = session.get(SqlProjectTask, parent.task_id)
        if task is None or task.archived_at is not None:
            raise RepositoryError("task_archived")
    if parent.created_by_user_id != requested_by_user_id:
        raise SessionStateError("only the private session creator may request a run")
    request_id = client_request_id or uuid4()
    existing_run = session.scalar(
        select(SqlAgentRun).where(
            SqlAgentRun.session_id == parent.id,
            SqlAgentRun.client_request_id == request_id,
        )
    )
    if existing_run is not None:
        existing_message = session.get(SqlAgentMessage, existing_run.request_message_id)
        if (
            existing_message is None
            or existing_run.requested_by_user_id != requested_by_user_id
            or existing_run.gateway_profile_id != gateway_profile_id
            or existing_message.content_md != content_md
            or existing_run.requested_context_revision_ids
            != [str(value) for value in context_revision_ids or []]
            or existing_run.requested_context_artifact_ids
            != [str(value) for value in context_artifact_ids or []]
            or run_grants.requested(session, existing_run.id) != requested_authority
        ):
            session.rollback()
            raise SessionStateError("idempotency key reused with different turn")
        if requested_authority is not None:
            run_grants.validate(
                session,
                project_id=existing_run.project_id,
                user_id=requested_by_user_id,
                agent_version_id=existing_run.agent_version_id,
                context_ids=context_revision_ids or [],
                authority=requested_authority,
            )
        session.commit()
        return existing_message, existing_run
    if execution_limits is not None:
        enforce_execution_limits(
            session,
            user_id=requested_by_user_id,
            project_id=parent.project_id,
            limits=execution_limits,
            now=_utc(now or utc_now()),
        )
    profile = _active_profile(session, profile_id=gateway_profile_id, user_id=requested_by_user_id)
    if runtime_spec is not None and profile.wire_api != "responses":
        raise SessionStateError("provider_protocol_incompatible")
    parent.next_message_sequence += 1
    parent.next_run_sequence += 1
    message = SqlAgentMessage(
        session_id=parent.id,
        sequence=parent.next_message_sequence,
        role=AgentMessageRole.USER,
        author_user_id=requested_by_user_id,
        content_md=content_md,
    )
    session.add(message)
    session.flush()
    run = SqlAgentRun(
        session_id=parent.id,
        project_id=parent.project_id,
        agent_version_id=parent.agent_version_id,
        requested_by_user_id=requested_by_user_id,
        request_message_id=message.id,
        client_request_id=request_id,
        gateway_profile_id=profile.id,
        gateway_credential_version=profile.credential_version,
        gateway_model_id=profile.model_id,
        runtime_spec=runtime_spec,
        queue_sequence=parent.next_run_sequence,
        input_message_sequence=message.sequence,
        requested_context_revision_ids=[str(value) for value in context_revision_ids or []],
        requested_context_artifact_ids=[str(value) for value in context_artifact_ids or []],
        deadline_at=deadline_at,
    )
    session.add(run)
    if requested_authority is not None:
        run_grants.attach(session, run, requested_authority)
    from polycolab.execution.allocator import admit

    admit(session, run)
    _commit(session)
    session.refresh(message)
    session.refresh(run)
    return message, run


def archive_agent_session(session: Session, *, session_id: UUID) -> SqlAgentSession:
    parent = _locked_session(session, session_id)
    if parent.status is AgentSessionStatus.ACTIVE:
        _archive_locked_session(session, parent, archived_at=utc_now())
        _commit(session)
    return parent


def _archive_locked_session(
    session: Session, parent: SqlAgentSession, *, archived_at: datetime
) -> None:
    """Archive a session and make every outstanding run durably non-executable."""

    parent.status = AgentSessionStatus.ARCHIVED
    parent.archived_at = archived_at
    runs = list(
        session.scalars(
            select(SqlAgentRun)
            .where(
                SqlAgentRun.session_id == parent.id,
                SqlAgentRun.status.not_in(_TERMINAL),
            )
            .with_for_update()
        )
    )
    for run in runs:
        _revoke_run_capabilities(session, run.id)
        if run.cancel_requested_at is None:
            run.cancel_requested_at = archived_at
            _append_event_locked(
                session,
                run=run,
                idempotency_key="cancel-requested-session-archive",
                kind=AgentRunEventKind.CANCEL_REQUESTED,
                payload={"code": "session_archived"},
                occurred_at=archived_at,
            )
        if run.status is AgentRunStatus.QUEUED:
            run.status = AgentRunStatus.CANCELLED
            run.finished_at = archived_at
            _append_event_locked(
                session,
                run=run,
                idempotency_key="run-cancelled-session-archive",
                kind=AgentRunEventKind.RUN_CANCELLED,
                payload={"code": "session_archived"},
                occurred_at=archived_at,
            )
        elif run.status in {AgentRunStatus.CLAIMED, AgentRunStatus.RUNNING}:
            run.status = AgentRunStatus.CANCELLING


def archive_project_agent_sessions(session: Session, *, project_id: UUID) -> list[SqlAgentSession]:
    """Project lifecycle hook: atomically stop every session and outstanding run."""

    archived_at = utc_now()
    parents = list(
        session.scalars(
            select(SqlAgentSession)
            .where(
                SqlAgentSession.project_id == project_id,
                SqlAgentSession.status == AgentSessionStatus.ACTIVE,
            )
            .with_for_update()
        )
    )
    for parent in parents:
        _archive_locked_session(session, parent, archived_at=archived_at)
    if parents:
        _commit(session)
    return parents


def _locked_run(session: Session, run_id: UUID) -> SqlAgentRun:
    parent_id = session.scalar(select(SqlAgentRun.session_id).where(SqlAgentRun.id == run_id))
    if parent_id is None:
        raise SessionNotFound
    # Session lifecycle and tool transactions use this same parent → run order.
    _locked_session(session, parent_id)
    result = session.scalar(
        select(SqlAgentRun)
        .where(SqlAgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise SessionNotFound
    return result


def _append_event_locked(
    session: Session,
    *,
    run: SqlAgentRun,
    idempotency_key: str,
    kind: AgentRunEventKind,
    payload: dict[str, object],
    occurred_at: datetime | None = None,
) -> SqlAgentRunEvent:
    if not idempotency_key or len(idempotency_key) > 200:
        raise SessionStateError("invalid event idempotency key")
    existing = session.scalar(
        select(SqlAgentRunEvent).where(
            SqlAgentRunEvent.run_id == run.id,
            SqlAgentRunEvent.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.kind is not kind or existing.payload != payload:
            raise IdempotencyConflict
        return existing
    run.next_event_cursor += 1
    event = SqlAgentRunEvent(
        run_id=run.id,
        cursor=run.next_event_cursor,
        idempotency_key=idempotency_key,
        kind=kind,
        payload=payload,
        occurred_at=occurred_at or utc_now(),
    )
    session.add(event)
    session.flush()
    return event


def _require_live_lease(
    run: SqlAgentRun, *, worker_id: str, lease_generation: int, now: datetime
) -> None:
    expires_at = run.lease_expires_at
    if (
        run.lease_owner != worker_id
        or run.lease_generation != lease_generation
        or run.status not in _LEASED
        or expires_at is None
        or _utc(expires_at) <= _utc(now)
    ):
        raise LeaseLost


def claim_next_run_in_transaction(
    session: Session,
    *,
    worker_id: str,
    lease_for: timedelta,
    now: datetime | None = None,
    engine: str | None = None,
    run_id: UUID | None = None,
) -> SqlAgentRun | None:
    """Mutate the earliest runnable run without committing the caller's transaction.

    A shared allocator can compose authorization, fairness charge and slot creation
    with this mutation. The caller owns commit/rollback; no external work may occur
    while the transaction remains open.
    """

    if not worker_id or lease_for <= timedelta(0):
        raise ValueError("worker_id and positive lease are required")
    claimed_at = _utc(now or utc_now())
    earlier = aliased(SqlAgentRun)
    earlier_session = aliased(SqlAgentSession)
    earlier_active = exists(
        select(earlier.id)
        .join(earlier_session, earlier_session.id == earlier.session_id)
        .where(
            earlier.status.not_in(_TERMINAL),
            or_(
                and_(
                    earlier.session_id == SqlAgentRun.session_id,
                    earlier.queue_sequence < SqlAgentRun.queue_sequence,
                ),
                and_(
                    SqlAgentSession.task_id.is_not(None),
                    earlier_session.task_id == SqlAgentSession.task_id,
                    earlier.id != SqlAgentRun.id,
                    or_(
                        earlier.status.in_(
                            [
                                AgentRunStatus.CLAIMED,
                                AgentRunStatus.RUNNING,
                                AgentRunStatus.CANCELLING,
                            ]
                        ),
                        and_(
                            earlier.status == AgentRunStatus.QUEUED,
                            or_(
                                earlier.created_at < SqlAgentRun.created_at,
                                and_(
                                    earlier.created_at == SqlAgentRun.created_at,
                                    earlier.id < SqlAgentRun.id,
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )
    query = (
        select(SqlAgentRun)
        .join(SqlAgentSession, SqlAgentSession.id == SqlAgentRun.session_id)
        .where(
            SqlAgentRun.status == AgentRunStatus.QUEUED,
            SqlAgentSession.status == AgentSessionStatus.ACTIVE,
            or_(
                SqlAgentSession.task_id.is_(None),
                exists(
                    select(SqlProjectTask.id).where(
                        SqlProjectTask.id == SqlAgentSession.task_id,
                        SqlProjectTask.archived_at.is_(None),
                    )
                ),
            ),
            ~earlier_active,
        )
        .order_by(SqlAgentRun.created_at, SqlAgentRun.id)
        .with_for_update(skip_locked=True, of=SqlAgentRun)
        .limit(1)
    )
    if engine is not None:
        query = query.where(
            SqlAgentRun.runtime_spec["engine"].as_string() == "codex"
            if engine == "codex"
            else SqlAgentRun.runtime_spec["engine"].as_string().is_(None)
        )
    if run_id is not None:
        query = query.where(SqlAgentRun.id == run_id)
    run = session.scalar(query)
    if run is None:
        return None
    if run.deadline_at is not None and _utc(run.deadline_at) <= claimed_at:
        run.status = AgentRunStatus.TIMED_OUT
        run.finished_at = claimed_at
        _append_event_locked(
            session,
            run=run,
            idempotency_key="deadline-before-claim",
            kind=AgentRunEventKind.RUN_TIMED_OUT,
            payload={"code": "deadline_exceeded"},
            occurred_at=claimed_at,
        )
        return None
    run.status = AgentRunStatus.CLAIMED
    run.lease_owner = worker_id
    run.lease_acquired_at = claimed_at
    run.lease_expires_at = (
        min(claimed_at + lease_for, _utc(run.deadline_at))
        if run.deadline_at
        else claimed_at + lease_for
    )
    run.lease_generation += 1
    run.attempt += 1
    return run


def claim_next_run(
    session: Session,
    *,
    worker_id: str,
    lease_for: timedelta,
    now: datetime | None = None,
    engine: str | None = None,
) -> SqlAgentRun | None:
    """Compatibility wrapper that commits one transaction-compatible claim."""

    run = claim_next_run_in_transaction(
        session, worker_id=worker_id, lease_for=lease_for, now=now, engine=engine
    )
    _commit(session)
    if run is not None:
        session.refresh(run)
    return run


def start_claimed_run(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    now: datetime | None = None,
) -> SqlAgentRun:
    started_at = _utc(now or utc_now())
    run = _locked_run(session, run_id)
    _require_live_lease(run, worker_id=worker_id, lease_generation=lease_generation, now=started_at)
    if run.status is not AgentRunStatus.CLAIMED:
        raise SessionStateError("run is not claimed")
    run.status = AgentRunStatus.RUNNING
    run.started_at = run.started_at or started_at
    _append_event_locked(
        session,
        run=run,
        idempotency_key=f"run-started-{run.lease_generation}",
        kind=AgentRunEventKind.RUN_STARTED,
        payload={"attempt": run.attempt},
        occurred_at=started_at,
    )
    agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
    if agent is None:
        raise SessionNotFound
    increment_durable(
        session,
        "polycolab_run_started_total",
        agent_kind=agent.agent_kind.value,
        outcome="started",
    )
    _commit(session)
    return run


def renew_lease(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    lease_for: timedelta,
    now: datetime | None = None,
) -> bool:
    renewed_at = _utc(now or utc_now())
    if lease_for <= timedelta(0):
        raise ValueError("lease must be positive")
    run = _locked_run(session, run_id)
    try:
        _require_live_lease(
            run, worker_id=worker_id, lease_generation=lease_generation, now=renewed_at
        )
    except LeaseLost:
        session.rollback()
        return False
    run.lease_expires_at = (
        min(renewed_at + lease_for, _utc(run.deadline_at))
        if run.deadline_at
        else renewed_at + lease_for
    )
    from polycolab.db.models import SqlExecutionSlotLease

    slot = session.scalar(
        select(SqlExecutionSlotLease).where(
            SqlExecutionSlotLease.agent_run_id == run.id,
            SqlExecutionSlotLease.generation == run.lease_generation,
            SqlExecutionSlotLease.released_at.is_(None),
        )
    )
    if slot is not None:
        slot.lease_expires_at = run.lease_expires_at
    _commit(session)
    return True


def append_worker_event(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    idempotency_key: str,
    kind: AgentRunEventKind,
    payload: dict[str, object],
    now: datetime | None = None,
) -> SqlAgentRunEvent:
    observed_at = _utc(now or utc_now())
    if kind not in _WORKER_EVENT_KINDS:
        raise SessionStateError("worker cannot emit lifecycle events directly")
    run = _locked_run(session, run_id)
    try:
        _require_live_lease(
            run, worker_id=worker_id, lease_generation=lease_generation, now=observed_at
        )
        event = _append_event_locked(
            session,
            run=run,
            idempotency_key=idempotency_key,
            kind=kind,
            payload=payload,
            occurred_at=observed_at,
        )
        if kind is AgentRunEventKind.ASSISTANT_DELTA and run.started_at is not None:
            # The first committed delta is the only client-relevant TTFT marker.
            existing_delta = session.scalar(
                select(SqlAgentRunEvent.id)
                .where(
                    SqlAgentRunEvent.run_id == run.id,
                    SqlAgentRunEvent.kind == AgentRunEventKind.ASSISTANT_DELTA,
                )
                .limit(1)
            )
            if existing_delta == event.id:
                agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
                if agent is None:
                    raise SessionNotFound
                observe_durable(
                    session,
                    "polycolab_run_time_to_first_token_seconds",
                    (_utc(observed_at) - _utc(run.started_at)).total_seconds(),
                    agent_kind=agent.agent_kind.value,
                    outcome="first_delta",
                )
        _commit(session)
        return event
    except Exception:
        session.rollback()
        raise


def record_usage(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    source: UsageSource,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    idempotency_key: str,
    now: datetime | None = None,
    input_microusd_per_million_tokens: int = 0,
    output_microusd_per_million_tokens: int = 0,
) -> SqlAgentRunUsage:
    observed_at = _utc(now or utc_now())
    if any(
        value is not None and value < 0 for value in (input_tokens, output_tokens, total_tokens)
    ):
        raise SessionStateError("usage counts must be non-negative")
    run = _locked_run(session, run_id)
    try:
        _require_live_lease(
            run, worker_id=worker_id, lease_generation=lease_generation, now=observed_at
        )
        event = _append_event_locked(
            session,
            run=run,
            idempotency_key=idempotency_key,
            kind=AgentRunEventKind.USAGE_REPORTED,
            payload={
                "source": source.value,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            },
            occurred_at=observed_at,
        )
        existing = session.scalar(
            select(SqlAgentRunUsage).where(
                SqlAgentRunUsage.run_id == run.id,
                SqlAgentRunUsage.event_cursor == event.cursor,
            )
        )
        if existing is not None:
            _commit(session)
            return existing
        usage = SqlAgentRunUsage(
            run_id=run.id,
            event_cursor=event.cursor,
            source=source,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            observed_at=observed_at,
        )
        session.add(usage)
        _commit(session)
        session.refresh(usage)
        metrics.increment("polycolab_usage_reports_total", source=source.value)
        if input_tokens is not None:
            metrics.increment("polycolab_usage_tokens_total", input_tokens, kind="input")
        if output_tokens is not None:
            metrics.increment("polycolab_usage_tokens_total", output_tokens, kind="output")
        if total_tokens is not None:
            metrics.increment("polycolab_usage_tokens_total", total_tokens, kind="total")
        estimated_cost = (
            (input_tokens or 0) * input_microusd_per_million_tokens
            + (output_tokens or 0) * output_microusd_per_million_tokens
        ) // 1_000_000
        if estimated_cost:
            metrics.increment("polycolab_usage_cost_microusd_total", estimated_cost)
        return usage
    except Exception:
        session.rollback()
        raise


def request_cancel(session: Session, *, run_id: UUID, now: datetime | None = None) -> SqlAgentRun:
    """Durably record cancellation; queued work becomes terminal without inference."""

    cancelled_at = _utc(now or utc_now())
    run = _locked_run(session, run_id)
    if run.status in _TERMINAL:
        return run
    if run.cancel_requested_at is None:
        run.cancel_requested_at = cancelled_at
        _append_event_locked(
            session,
            run=run,
            idempotency_key="cancel-requested",
            kind=AgentRunEventKind.CANCEL_REQUESTED,
            payload={},
            occurred_at=cancelled_at,
        )
    if run.status is AgentRunStatus.QUEUED:
        run.status = AgentRunStatus.CANCELLED
        run.finished_at = cancelled_at
        _append_event_locked(
            session,
            run=run,
            idempotency_key="run-cancelled-before-claim",
            kind=AgentRunEventKind.RUN_CANCELLED,
            payload={"code": "cancelled_before_claim"},
            occurred_at=cancelled_at,
        )
    elif run.status in {AgentRunStatus.CLAIMED, AgentRunStatus.RUNNING}:
        run.status = AgentRunStatus.CANCELLING
    _commit(session)
    if run.status is AgentRunStatus.CANCELLED:
        metrics.increment(
            "polycolab_run_terminal_total", agent_kind="platform", outcome="CANCELLED"
        )
    return run


def finish_run(
    session: Session,
    *,
    run_id: UUID,
    worker_id: str,
    lease_generation: int,
    status: AgentRunStatus,
    failure_code: str | None = None,
    final_message_md: str | None = None,
    now: datetime | None = None,
) -> SqlAgentRun:
    """Write a terminal state and optional immutable assistant message atomically."""

    finished_at = _utc(now or utc_now())
    if status not in _TERMINAL:
        raise ValueError("status must be terminal")
    run = _locked_run(session, run_id)
    try:
        _require_live_lease(
            run, worker_id=worker_id, lease_generation=lease_generation, now=finished_at
        )
        if status is AgentRunStatus.COMPLETED and run.status is not AgentRunStatus.RUNNING:
            raise SessionStateError("only a running run can complete")
        if run.status is AgentRunStatus.CANCELLING and status not in {
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
            AgentRunStatus.TIMED_OUT,
        }:
            raise SessionStateError("invalid transition from cancelling")
        if status is AgentRunStatus.COMPLETED and not final_message_md:
            raise SessionStateError("completed run requires final message")
        if status is not AgentRunStatus.COMPLETED and final_message_md is not None:
            raise SessionStateError("only completed runs may create an assistant message")
        if status is AgentRunStatus.COMPLETED and run.runtime_spec:
            from polycolab.db.models import SqlArtifact, SqlHostedRunArtifact
            from polycolab.entities.enums import ArtifactState

            outputs = session.scalars(
                select(SqlArtifact)
                .join(SqlHostedRunArtifact)
                .where(
                    SqlHostedRunArtifact.run_id == run.id,
                    SqlHostedRunArtifact.generation == lease_generation,
                )
                .with_for_update(of=SqlArtifact)
            )
            for artifact in outputs:
                if artifact.state != ArtifactState.STAGING or artifact.verified_at is None:
                    raise SessionStateError("hosted artifact upload incomplete")
                artifact.state = ArtifactState.COMMITTED
                artifact.committed_at = finished_at
        run.status = status
        run.finished_at = finished_at
        run.failure_code = failure_code
        run.lease_owner = None
        run.lease_expires_at = None
        _revoke_run_capabilities(session, run.id)
        if final_message_md:
            parent = _locked_session(session, run.session_id)
            parent.next_message_sequence += 1
            message = SqlAgentMessage(
                session_id=parent.id,
                sequence=parent.next_message_sequence,
                role=AgentMessageRole.AGENT,
                author_user_id=None,
                content_md=final_message_md,
            )
            session.add(message)
            session.flush()
            _append_event_locked(
                session,
                run=run,
                idempotency_key=f"assistant-message-{lease_generation}",
                kind=AgentRunEventKind.ASSISTANT_MESSAGE_COMPLETED,
                payload={"message_id": str(message.id), "sequence": message.sequence},
                occurred_at=finished_at,
            )
        event_kind = {
            AgentRunStatus.COMPLETED: AgentRunEventKind.RUN_COMPLETED,
            AgentRunStatus.CANCELLED: AgentRunEventKind.RUN_CANCELLED,
            AgentRunStatus.FAILED: AgentRunEventKind.RUN_FAILED,
            AgentRunStatus.TIMED_OUT: AgentRunEventKind.RUN_TIMED_OUT,
        }[status]
        _append_event_locked(
            session,
            run=run,
            idempotency_key=f"terminal-{status.value.lower()}-{lease_generation}",
            kind=event_kind,
            payload={"code": failure_code} if failure_code else {},
            occurred_at=finished_at,
        )
        agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
        if agent is None:
            raise SessionNotFound
        increment_durable(
            session,
            "polycolab_run_terminal_total",
            agent_kind=agent.agent_kind.value,
            outcome=status.value,
        )
        if run.started_at is not None:
            observe_durable(
                session,
                "polycolab_run_duration_seconds",
                (_utc(finished_at) - _utc(run.started_at)).total_seconds(),
                agent_kind=agent.agent_kind.value,
                outcome=status.value,
            )
        # Terminal run failures are not provider-request counts. Provider I/O
        # is metered at the private model gateway where an actual request opens.
        _commit(session)
        return run
    except Exception:
        session.rollback()
        raise


def requeue_expired_runs(
    session: Session,
    *,
    max_attempts: int,
    now: datetime | None = None,
) -> list[SqlAgentRun]:
    """Recover lost workers while preventing stale generations from appending history."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    recovered_at = _utc(now or utc_now())
    runs = list(
        session.scalars(
            select(SqlAgentRun)
            .where(
                SqlAgentRun.status.in_(_LEASED),
                SqlAgentRun.runtime_spec["engine"].as_string().is_(None),
                SqlAgentRun.lease_expires_at.is_not(None),
                SqlAgentRun.lease_expires_at <= recovered_at,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for run in runs:
        _revoke_run_capabilities(session, run.id)
        _append_event_locked(
            session,
            run=run,
            idempotency_key=f"runner-lost-{run.lease_generation}",
            kind=AgentRunEventKind.RUNNER_LOST,
            payload={"attempt": run.attempt},
            occurred_at=recovered_at,
        )
        run.lease_owner = None
        run.lease_expires_at = None
        if run.status is AgentRunStatus.CANCELLING:
            run.status = AgentRunStatus.CANCELLED
            run.finished_at = recovered_at
            _append_event_locked(
                session,
                run=run,
                idempotency_key=f"run-cancelled-after-loss-{run.lease_generation}",
                kind=AgentRunEventKind.RUN_CANCELLED,
                payload={"code": "cancelled_after_runner_loss"},
                occurred_at=recovered_at,
            )
        elif run.attempt >= (
            int(str(run.runtime_spec.get("max_attempts", max_attempts)))
            if run.runtime_spec
            else max_attempts
        ):
            run.status = AgentRunStatus.FAILED
            run.finished_at = recovered_at
            run.failure_code = "runner_lost"
            _append_event_locked(
                session,
                run=run,
                idempotency_key=f"run-failed-after-loss-{run.lease_generation}",
                kind=AgentRunEventKind.RUN_FAILED,
                payload={"code": "runner_lost"},
                occurred_at=recovered_at,
            )
        else:
            run.status = AgentRunStatus.QUEUED
        increment_durable(
            session,
            "polycolab_run_lease_recovered_total",
            outcome=run.status.value,
        )
    if runs:
        _commit(session)
    return runs


def resume_run(
    session: Session,
    *,
    run_id: UUID,
    requested_by_user_id: UUID,
    gateway_profile_id: UUID,
    client_request_id: UUID | None = None,
    deadline_at: datetime | None = None,
    execution_limits: ExecutionLimits | None = None,
    now: datetime | None = None,
    runtime_spec: dict[str, object] | None = None,
) -> SqlAgentRun:
    """Resume creates a successor intent; historical terminal runs never reopen."""

    previous = _locked_run(session, run_id)
    if previous.status not in _TERMINAL:
        raise SessionStateError("only terminal runs can be resumed")
    parent = _locked_session(session, previous.session_id)
    if parent.status is not AgentSessionStatus.ACTIVE:
        raise SessionStateError("session is archived")
    if parent.task_id is not None:
        task = session.get(SqlProjectTask, parent.task_id)
        if task is None or task.archived_at is not None:
            raise RepositoryError("task_archived")
    if (
        parent.created_by_user_id != requested_by_user_id
        or previous.requested_by_user_id != requested_by_user_id
    ):
        raise SessionStateError("only the private session creator may resume a run")
    request_id = client_request_id or uuid4()
    existing = session.scalar(
        select(SqlAgentRun).where(
            SqlAgentRun.session_id == parent.id,
            SqlAgentRun.client_request_id == request_id,
        )
    )
    if existing is not None:
        if (
            existing.parent_run_id != previous.id
            or existing.requested_by_user_id != requested_by_user_id
            or existing.gateway_profile_id != gateway_profile_id
        ):
            session.rollback()
            raise SessionStateError("idempotency key reused with different resume")
        authority = run_grants.requested(session, existing.id)
        if authority is not None:
            run_grants.validate(
                session,
                project_id=existing.project_id,
                user_id=requested_by_user_id,
                agent_version_id=existing.agent_version_id,
                context_ids=[UUID(value) for value in existing.requested_context_revision_ids],
                authority=authority,
            )
        session.commit()
        return existing
    if execution_limits is not None:
        enforce_execution_limits(
            session,
            user_id=requested_by_user_id,
            project_id=parent.project_id,
            limits=execution_limits,
            now=_utc(now or utc_now()),
        )
    profile = _active_profile(session, profile_id=gateway_profile_id, user_id=requested_by_user_id)
    if runtime_spec is not None and profile.wire_api != "responses":
        raise SessionStateError("provider_protocol_incompatible")
    parent.next_run_sequence += 1
    successor = SqlAgentRun(
        session_id=parent.id,
        project_id=parent.project_id,
        agent_version_id=parent.agent_version_id,
        requested_by_user_id=requested_by_user_id,
        parent_run_id=previous.id,
        client_request_id=request_id,
        gateway_profile_id=profile.id,
        gateway_credential_version=profile.credential_version,
        gateway_model_id=profile.model_id,
        runtime_spec=runtime_spec,
        queue_sequence=parent.next_run_sequence,
        input_message_sequence=parent.next_message_sequence,
        requested_context_revision_ids=previous.requested_context_revision_ids,
        requested_context_artifact_ids=previous.requested_context_artifact_ids,
        deadline_at=deadline_at,
    )
    session.add(successor)
    authority = run_grants.requested(session, previous.id)
    if authority is not None:
        run_grants.attach(session, successor, authority)
    from polycolab.execution.allocator import admit

    admit(session, successor)
    _commit(session)
    session.refresh(successor)
    return successor


def activate_runtime_session_binding(
    session: Session,
    *,
    session_id: UUID,
    adapter_name: str,
    opaque_runtime_ref: str | None = None,
) -> SqlRuntimeSessionBinding:
    """Supersede prior active binding atomically; refs remain private adapter metadata."""

    _locked_session(session, session_id)
    active = list(
        session.scalars(
            select(SqlRuntimeSessionBinding)
            .where(
                SqlRuntimeSessionBinding.session_id == session_id,
                SqlRuntimeSessionBinding.status == RuntimeBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
    )
    for binding in active:
        binding.status = RuntimeBindingStatus.SUPERSEDED
        binding.ended_at = utc_now()
    binding = SqlRuntimeSessionBinding(
        session_id=session_id,
        adapter_name=adapter_name,
        opaque_runtime_ref=opaque_runtime_ref,
    )
    session.add(binding)
    _commit(session)
    session.refresh(binding)
    return binding


def create_runtime_run_binding(
    session: Session,
    *,
    run_id: UUID,
    session_binding_id: UUID,
    adapter_name: str,
    opaque_runtime_ref: str | None = None,
) -> SqlRuntimeRunBinding:
    run = _locked_run(session, run_id)
    binding = session.scalar(
        select(SqlRuntimeSessionBinding)
        .where(
            SqlRuntimeSessionBinding.id == session_binding_id,
            SqlRuntimeSessionBinding.session_id == run.session_id,
        )
        .with_for_update()
    )
    if binding is None:
        raise SessionStateError("runtime session binding belongs to another session")
    existing = session.scalar(
        select(SqlRuntimeRunBinding).where(SqlRuntimeRunBinding.run_id == run.id).with_for_update()
    )
    if existing is not None:
        raise SessionStateError("run already has a runtime binding")
    result = SqlRuntimeRunBinding(
        run_id=run.id,
        session_id=run.session_id,
        session_binding_id=binding.id,
        adapter_name=adapter_name,
        opaque_runtime_ref=opaque_runtime_ref,
    )
    session.add(result)
    _commit(session)
    session.refresh(result)
    return result

"""Transactional canonical session/run state for the WP-09 built-in worker.

Owns ordered conversation history and lease-safe execution state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session, aliased

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.conversations.service import (
    ConversationStateError as ConversationStateError,
)
from polycolab.conversations.service import (
    can_execute,
    require_owner,
    require_submit,
)
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentRunUsage,
    SqlConversation,
    SqlConversationConfiguration,
    SqlConversationItem,
    SqlPlatformAgentVersion,
    SqlProviderConnection,
    SqlRuntimeRunBinding,
    SqlRuntimeSessionBinding,
    SqlRunToolCapability,
)
from polycolab.db.models.projects import SqlProject
from polycolab.db.models.worktrees import SqlWorktree
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.conversation import Conversation, ConversationStatus
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunEventKind,
    AgentRunStatus,
    ExecutionProfile,
    PlatformAgentKind,
    RuntimeBindingStatus,
    StoredConversationStatus,
    UsageSource,
)
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.execution.limits import ExecutionLimits, enforce_execution_limits
from polycolab.platform.observability import increment_durable, metrics, observe_durable


class ConversationNotFound(Exception):
    """Raised by the domain layer; HTTP authorization decides disclosure."""


class LeaseLost(ConversationStateError):
    """An event or transition came from a worker whose lease is no longer valid."""


class IdempotencyConflict(ConversationStateError):
    """An idempotency key was reused for a different immutable operation."""


class ExecutionAuthorityLost(ConversationStateError):
    """The sender can no longer execute in the session."""


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
_PLATFORM_V3: tuple[tuple[UUID, PlatformAgentKind, str, str], ...] = (
    (
        UUID("a0000000-0000-4000-8000-000000000005"),
        PlatformAgentKind.RESEARCHER,
        "Researcher",
        "Explore problems and work with the project files. Read before editing; "
        "explain changes and distinguish observed results from assumptions.",
    ),
    (
        UUID("a0000000-0000-4000-8000-000000000006"),
        PlatformAgentKind.CRITIC,
        "Critic",
        "Review project work for gaps, hidden assumptions, and counterexamples. "
        "Explain findings and the evidence supporting them.",
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
    """Seed immutable agent specifications, preserving existing session bindings."""

    changed = False
    for version, entries in enumerate((_PLATFORM_V1, _PLATFORM_V2, _PLATFORM_V3), start=1):
        for version_id, kind, display_name, instructions in entries:
            existing = session.get(SqlPlatformAgentVersion, version_id)
            if existing is None:
                session.add(
                    SqlPlatformAgentVersion(
                        id=version_id,
                        agent_kind=kind,
                        version=version,
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
        raise ConversationNotFound
    return agent_version


def create_agent_conversation(
    session: Session,
    *,
    project_id: UUID,
    created_by_user_id: UUID,
    agent_kind: PlatformAgentKind,
    title: str | None = None,
    version: int = 1,
    harness: Literal["codex"] | None = None,
    system_prompt: str | None = None,
    worktree_id: UUID | None = None,
) -> SqlConversation:
    """Create a private project session pinned to an eligible agent definition."""

    agent_version = platform_agent_version(session, agent_kind=agent_kind, version=version)
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, created_by_user_id, ProjectAction.RUN_AGENTS
    )
    project = session.get(SqlProject, project_id)
    if project is not None and project.file_mode in {"collaborative", "basic"}:
        worktree_id = None
    elif worktree_id is None:
        worktree_id = session.scalar(
            select(SqlWorktree.id).where(
                SqlWorktree.project_id == project_id, SqlWorktree.branch == "main"
            )
        )
    if worktree_id is not None:
        task = session.scalar(
            select(SqlWorktree)
            .where(SqlWorktree.id == worktree_id, SqlWorktree.project_id == project_id)
            .with_for_update()
        )
        if task is None:
            raise RepositoryError("worktree_not_found", 404)
        if task.removed_at is not None:
            raise RepositoryError("worktree_removed")
    result = SqlConversation(
        worktree_id=worktree_id,
        project_id=project_id,
        configuration=SqlConversationConfiguration(
            agent_version_id=agent_version.id,
            agent_display_name=agent_version.display_name,
            agent_kind=agent_version.agent_kind.value,
            agent_version=agent_version.version,
            harness=harness or "platform",
            system_prompt=system_prompt,
        ),
        created_by_user_id=created_by_user_id,
        title=title,
    )
    session.add(result)
    _commit(session)
    session.refresh(result)
    return result


def _locked_conversation(session: Session, conversation_id: UUID) -> SqlConversation:
    worktree_id = session.scalar(
        select(SqlConversation.worktree_id).where(SqlConversation.id == conversation_id)
    )
    if worktree_id is not None:
        session.scalar(
            select(SqlWorktree)
            .where(SqlWorktree.id == worktree_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    result = session.scalar(
        select(SqlConversation)
        .where(SqlConversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise ConversationNotFound
    return result


def _active_connection(
    session: Session, *, provider_connection_id: UUID, user_id: UUID
) -> SqlProviderConnection:
    connection = session.scalar(
        select(SqlProviderConnection)
        .where(
            SqlProviderConnection.id == provider_connection_id,
            SqlProviderConnection.user_id == user_id,
            SqlProviderConnection.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if connection is None:
        raise ConversationStateError("provider connection is unavailable")
    return connection


def accepted_user_message(
    session: Session,
    *,
    conversation_id: UUID,
    requested_by_user_id: UUID,
    provider_connection_id: UUID,
    content_md: str,
    context_artifact_ids: list[UUID] | None,
    client_request_id: UUID,
) -> tuple[SqlConversationItem, SqlAgentRun] | None:
    """Read a matching durable admission. The caller first checks current read access."""
    existing_run = session.scalar(
        select(SqlAgentRun).where(
            SqlAgentRun.conversation_id == conversation_id,
            SqlAgentRun.client_request_id == client_request_id,
        )
    )
    if existing_run is not None:
        existing_message = session.get(SqlConversationItem, existing_run.request_message_id)
        if (
            existing_message is None
            or existing_run.requested_by_user_id != requested_by_user_id
            or existing_run.provider_connection_id != provider_connection_id
            or existing_message.content_md != content_md
            or existing_run.requested_context_artifact_ids
            != [str(value) for value in context_artifact_ids or []]
        ):
            session.rollback()
            raise ConversationStateError("idempotency key reused with different turn")
        return existing_message, existing_run
    return None


def append_user_message_and_queue_run(
    session: Session,
    *,
    conversation_id: UUID,
    requested_by_user_id: UUID,
    provider_connection_id: UUID,
    content_md: str,
    context_artifact_ids: list[UUID] | None = None,
    client_request_id: UUID | None = None,
    deadline_at: datetime | None = None,
    execution_limits: ExecutionLimits | None = None,
    now: datetime | None = None,
    runtime_spec: dict[str, object] | None = None,
) -> tuple[SqlConversationItem, SqlAgentRun]:
    """Append a human message and its ordered run atomically.

    The requester-owned connection's model and credential version are copied to the
    durable run; no secret or run grant is persisted.
    """

    if not content_md.strip():
        raise ConversationStateError("message must not be empty")
    require_submit(SqlAlchemyTransaction(session), conversation_id, requested_by_user_id)
    parent = _locked_conversation(session, conversation_id)
    require_submit(SqlAlchemyTransaction(session), conversation_id, requested_by_user_id)
    if parent.origin != "agent" or parent.project_id is None:
        raise ConversationStateError("legacy history is read-only")
    if parent.configuration is None or parent.configuration.harness not in {"platform", "codex"}:
        raise ConversationStateError("unsupported harness")
    from polycolab.db.stores.collaborative import SqlCollaborativeStore

    collaborative_project = session.get(SqlProject, parent.project_id)
    if parent.project_id is not None and SqlCollaborativeStore(session).conversion_pending(
        parent.project_id
    ):
        raise RepositoryError("collaborative_conversion_in_progress")
    if parent.status is not StoredConversationStatus.ACTIVE:
        raise ConversationStateError("conversation is archived")
    if parent.worktree_id is not None and (
        collaborative_project is None
        or collaborative_project.file_mode not in {"collaborative", "basic"}
    ):
        task = session.get(SqlWorktree, parent.worktree_id)
        if task is None or task.removed_at is not None:
            raise RepositoryError("worktree_removed")
    request_id = client_request_id or uuid4()
    accepted = accepted_user_message(
        session,
        conversation_id=parent.id,
        requested_by_user_id=requested_by_user_id,
        provider_connection_id=provider_connection_id,
        content_md=content_md,
        context_artifact_ids=context_artifact_ids,
        client_request_id=request_id,
    )
    if accepted is not None:
        session.commit()
        return accepted
    if execution_limits is not None:
        enforce_execution_limits(
            session,
            user_id=requested_by_user_id,
            project_id=parent.project_id,
            limits=execution_limits,
            now=_utc(now or utc_now()),
        )
    connection = _active_connection(
        session, provider_connection_id=provider_connection_id, user_id=requested_by_user_id
    )
    if runtime_spec is not None and connection.wire_api != "responses":
        raise ConversationStateError("provider_protocol_incompatible")
    run_id = uuid4()
    parent.next_message_sequence += 1
    parent.next_run_sequence += 1
    message = SqlConversationItem(
        conversation_id=parent.id,
        sequence=parent.next_message_sequence,
        role=AgentMessageRole.USER,
        execution_id=run_id,
        author_user_id=requested_by_user_id,
        content_md=content_md,
    )
    session.add(message)
    session.flush()
    run = SqlAgentRun(
        id=run_id,
        conversation_id=parent.id,
        project_id=parent.project_id,
        agent_version_id=parent.agent_version_id,
        requested_by_user_id=requested_by_user_id,
        request_message_id=message.id,
        client_request_id=request_id,
        provider_connection_id=connection.id,
        gateway_credential_version=connection.credential_version,
        gateway_model_id=connection.model_id,
        runtime_spec=runtime_spec,
        queue_sequence=parent.next_run_sequence,
        input_message_sequence=message.sequence,
        requested_context_artifact_ids=[str(value) for value in context_artifact_ids or []],
        deadline_at=deadline_at,
    )
    session.add(run)
    from polycolab.execution.allocator import admit

    admit(session, run)
    _commit(session)
    session.refresh(message)
    session.refresh(run)
    return message, run


def update_conversation_metadata(
    session: Session,
    *,
    conversation_id: UUID,
    user_id: UUID,
    title: str | None,
    change_title: bool,
    archived: bool | None,
) -> Conversation:
    transaction = SqlAlchemyTransaction(session)
    require_owner(transaction, conversation_id, user_id)
    parent = _locked_conversation(session, conversation_id)
    current = require_owner(transaction, conversation_id, user_id)
    now = utc_now()
    if archived and parent.origin == "agent":
        from polycolab.db.stores.collaborative import SqlCollaborativeStore

        if parent.project_id is not None and SqlCollaborativeStore(session).conversion_pending(
            parent.project_id
        ):
            raise RepositoryError("collaborative_conversion_in_progress")
        if parent.status is StoredConversationStatus.ACTIVE:
            _archive_locked_conversation(session, parent, archived_at=now)
    value = transaction.conversations.set_metadata(
        conversation_id,
        title=title if change_title else current.title,
        status=(ConversationStatus.ARCHIVED if archived else ConversationStatus.ACTIVE)
        if archived is not None
        else current.status,
        updated_at=now,
    )
    transaction.commit()
    return value


def archive_agent_conversation(session: Session, *, conversation_id: UUID) -> SqlConversation:
    parent = _locked_conversation(session, conversation_id)
    from polycolab.db.stores.collaborative import SqlCollaborativeStore

    if parent.project_id is not None and SqlCollaborativeStore(session).conversion_pending(
        parent.project_id
    ):
        raise RepositoryError("collaborative_conversion_in_progress")
    if parent.status is StoredConversationStatus.ACTIVE:
        _archive_locked_conversation(session, parent, archived_at=utc_now())
        _commit(session)
    return parent


def _archive_locked_conversation(
    session: Session, parent: SqlConversation, *, archived_at: datetime
) -> None:
    """Archive a session and make every outstanding run durably non-executable."""

    parent.status = StoredConversationStatus.ARCHIVED
    parent.archived_at = archived_at
    runs = list(
        session.scalars(
            select(SqlAgentRun)
            .where(
                SqlAgentRun.conversation_id == parent.id,
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


def archive_project_conversations(session: Session, *, project_id: UUID) -> list[SqlConversation]:
    """Project lifecycle hook: atomically stop every session and outstanding run."""

    archived_at = utc_now()
    parents = list(
        session.scalars(
            select(SqlConversation)
            .where(
                SqlConversation.project_id == project_id,
                SqlConversation.status == StoredConversationStatus.ACTIVE,
            )
            .with_for_update()
        )
    )
    for parent in parents:
        _archive_locked_conversation(session, parent, archived_at=archived_at)
    if parents:
        _commit(session)
    return parents


def _locked_run(session: Session, run_id: UUID) -> SqlAgentRun:
    parent_id = session.scalar(select(SqlAgentRun.conversation_id).where(SqlAgentRun.id == run_id))
    if parent_id is None:
        raise ConversationNotFound
    # Session lifecycle and tool transactions use this same parent → run order.
    _locked_conversation(session, parent_id)
    result = session.scalar(
        select(SqlAgentRun)
        .where(SqlAgentRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if result is None:
        raise ConversationNotFound
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
        raise ConversationStateError("invalid event idempotency key")
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
    from polycolab.conversations.events import semantic_payload
    from polycolab.db.stores.conversations import SqlConversationStore
    from polycolab.entities.conversation import (
        AgentAuthor,
        SystemAuthor,
        ToolAuthor,
        ToolCallData,
        ToolResultData,
    )

    data = semantic_payload(kind, payload)
    if data is not None:
        SqlConversationStore(session).append_item(
            run.conversation_id,
            item_id=uuid5(event.id, "conversation-item"),
            author=(
                AgentAuthor(run.agent_version_id)
                if isinstance(data, ToolCallData)
                else ToolAuthor(data.name, run.agent_version_id)
                if isinstance(data, ToolResultData)
                else SystemAuthor()
            ),
            data=data,
            execution_id=run.id,
            created_at=event.occurred_at,
        )
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
    earlier_session = aliased(SqlConversation)
    earlier_active = exists(
        select(earlier.id)
        .join(earlier_session, earlier_session.id == earlier.conversation_id)
        .where(
            earlier.status.not_in(_TERMINAL),
            or_(
                and_(
                    earlier.conversation_id == SqlAgentRun.conversation_id,
                    earlier.queue_sequence < SqlAgentRun.queue_sequence,
                ),
                and_(
                    SqlConversation.worktree_id.is_not(None),
                    ~exists(
                        select(SqlProject.id).where(
                            SqlProject.id == SqlAgentRun.project_id,
                            SqlProject.file_mode.in_(["collaborative", "basic"]),
                        )
                    ),
                    earlier_session.worktree_id == SqlConversation.worktree_id,
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
        .join(SqlConversation, SqlConversation.id == SqlAgentRun.conversation_id)
        .where(
            SqlAgentRun.status == AgentRunStatus.QUEUED,
            SqlConversation.status == StoredConversationStatus.ACTIVE,
            or_(
                SqlConversation.worktree_id.is_(None),
                exists(
                    select(SqlProject.id).where(
                        SqlProject.id == SqlAgentRun.project_id,
                        SqlProject.file_mode.in_(["collaborative", "basic"]),
                    )
                ),
                exists(
                    select(SqlWorktree.id).where(
                        SqlWorktree.id == SqlConversation.worktree_id,
                        SqlWorktree.removed_at.is_(None),
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
        raise ConversationStateError("run is not claimed")
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
        raise ConversationNotFound
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
        raise ConversationStateError("worker cannot emit lifecycle events directly")
    run = _locked_run(session, run_id)
    try:
        _require_live_lease(
            run, worker_id=worker_id, lease_generation=lease_generation, now=observed_at
        )
        if not can_execute(
            SqlAlchemyTransaction(session), run.conversation_id, run.requested_by_user_id
        ):
            raise ExecutionAuthorityLost
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
                    raise ConversationNotFound
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
        raise ConversationStateError("usage counts must be non-negative")
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
        if status is AgentRunStatus.COMPLETED and not can_execute(
            SqlAlchemyTransaction(session), run.conversation_id, run.requested_by_user_id
        ):
            raise ExecutionAuthorityLost
        if status is AgentRunStatus.COMPLETED and run.status is not AgentRunStatus.RUNNING:
            raise ConversationStateError("only a running run can complete")
        if run.status is AgentRunStatus.CANCELLING and status not in {
            AgentRunStatus.CANCELLED,
            AgentRunStatus.FAILED,
            AgentRunStatus.TIMED_OUT,
        }:
            raise ConversationStateError("invalid transition from cancelling")
        if status is AgentRunStatus.COMPLETED and not final_message_md:
            raise ConversationStateError("completed run requires final message")
        if status is not AgentRunStatus.COMPLETED and final_message_md is not None:
            raise ConversationStateError("only completed runs may create an assistant message")
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
                    raise ConversationStateError("hosted artifact upload incomplete")
                artifact.state = ArtifactState.COMMITTED
                artifact.committed_at = finished_at
        run.status = status
        run.finished_at = finished_at
        run.failure_code = failure_code
        run.lease_owner = None
        run.lease_expires_at = None
        _revoke_run_capabilities(session, run.id)
        if final_message_md:
            parent = _locked_conversation(session, run.conversation_id)
            parent.next_message_sequence += 1
            message = SqlConversationItem(
                conversation_id=parent.id,
                sequence=parent.next_message_sequence,
                role=AgentMessageRole.AGENT,
                execution_id=run.id,
                agent_version_id=run.agent_version_id,
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
            raise ConversationNotFound
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
    provider_connection_id: UUID,
    client_request_id: UUID | None = None,
    deadline_at: datetime | None = None,
    execution_limits: ExecutionLimits | None = None,
    now: datetime | None = None,
    runtime_spec: dict[str, object] | None = None,
) -> SqlAgentRun:
    """Resume creates a successor intent; historical terminal runs never reopen."""

    previous = session.get(SqlAgentRun, run_id)
    if previous is None:
        raise ConversationNotFound
    require_submit(SqlAlchemyTransaction(session), previous.conversation_id, requested_by_user_id)
    previous = _locked_run(session, run_id)
    if previous.status not in _TERMINAL:
        raise ConversationStateError("only terminal runs can be resumed")
    parent = _locked_conversation(session, previous.conversation_id)
    if parent.project_id is None:
        raise ConversationStateError("legacy history is read-only")
    require_submit(SqlAlchemyTransaction(session), parent.id, requested_by_user_id)
    collaborative_project = session.get(SqlProject, parent.project_id)
    from polycolab.db.stores.collaborative import SqlCollaborativeStore

    if parent.project_id is not None and SqlCollaborativeStore(session).conversion_pending(
        parent.project_id
    ):
        raise RepositoryError("collaborative_conversion_in_progress")
    if parent.status is not StoredConversationStatus.ACTIVE:
        raise ConversationStateError("conversation is archived")
    if parent.worktree_id is not None and (
        collaborative_project is None
        or collaborative_project.file_mode not in {"collaborative", "basic"}
    ):
        task = session.get(SqlWorktree, parent.worktree_id)
        if task is None or task.removed_at is not None:
            raise RepositoryError("worktree_removed")
    if previous.requested_by_user_id != requested_by_user_id:
        raise ConversationStateError(
            "only the run sender may resume its private context and authority"
        )
    request_id = client_request_id or uuid4()
    existing = session.scalar(
        select(SqlAgentRun).where(
            SqlAgentRun.conversation_id == parent.id,
            SqlAgentRun.client_request_id == request_id,
        )
    )
    if existing is not None:
        if (
            existing.parent_run_id != previous.id
            or existing.requested_by_user_id != requested_by_user_id
            or existing.provider_connection_id != provider_connection_id
        ):
            session.rollback()
            raise ConversationStateError("idempotency key reused with different resume")
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
    connection = _active_connection(
        session, provider_connection_id=provider_connection_id, user_id=requested_by_user_id
    )
    if runtime_spec is not None and connection.wire_api != "responses":
        raise ConversationStateError("provider_protocol_incompatible")
    parent.next_run_sequence += 1
    successor = SqlAgentRun(
        conversation_id=parent.id,
        project_id=parent.project_id,
        agent_version_id=parent.agent_version_id,
        requested_by_user_id=requested_by_user_id,
        parent_run_id=previous.id,
        client_request_id=request_id,
        provider_connection_id=connection.id,
        gateway_credential_version=connection.credential_version,
        gateway_model_id=connection.model_id,
        runtime_spec=runtime_spec,
        queue_sequence=parent.next_run_sequence,
        input_message_sequence=parent.next_message_sequence,
        requested_context_artifact_ids=previous.requested_context_artifact_ids,
        deadline_at=deadline_at,
    )
    session.add(successor)
    from polycolab.execution.allocator import admit

    admit(session, successor)
    _commit(session)
    session.refresh(successor)
    return successor


def activate_runtime_session_binding(
    session: Session,
    *,
    conversation_id: UUID,
    adapter_name: str,
    opaque_runtime_ref: str | None = None,
) -> SqlRuntimeSessionBinding:
    """Supersede prior active binding atomically; refs remain private adapter metadata."""

    _locked_conversation(session, conversation_id)
    active = list(
        session.scalars(
            select(SqlRuntimeSessionBinding)
            .where(
                SqlRuntimeSessionBinding.conversation_id == conversation_id,
                SqlRuntimeSessionBinding.status == RuntimeBindingStatus.ACTIVE,
            )
            .with_for_update()
        )
    )
    for binding in active:
        binding.status = RuntimeBindingStatus.SUPERSEDED
        binding.ended_at = utc_now()
    binding = SqlRuntimeSessionBinding(
        conversation_id=conversation_id,
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
            SqlRuntimeSessionBinding.conversation_id == run.conversation_id,
        )
        .with_for_update()
    )
    if binding is None:
        raise ConversationStateError("runtime session binding belongs to another session")
    existing = session.scalar(
        select(SqlRuntimeRunBinding).where(SqlRuntimeRunBinding.run_id == run.id).with_for_update()
    )
    if existing is not None:
        raise ConversationStateError("run already has a runtime binding")
    result = SqlRuntimeRunBinding(
        run_id=run.id,
        conversation_id=run.conversation_id,
        session_binding_id=binding.id,
        adapter_name=adapter_name,
        opaque_runtime_ref=opaque_runtime_ref,
    )
    session.add(result)
    _commit(session)
    session.refresh(result)
    return result

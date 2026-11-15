"""One public conversation API over canonical conversations and durable run updates."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select, true

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectNotFound,
    project_policy,
)
from polycolab.agents.conversations import (
    accepted_user_message,
    append_user_message_and_queue_run,
    create_agent_conversation,
    ensure_platform_agent_versions,
    request_cancel,
    resume_run,
    update_conversation_metadata,
)
from polycolab.agents.schemas import AgentRunEventRead, PlatformAgentRead
from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.artifacts import service as artifacts
from polycolab.conversations.routes.presenters import conversation_read, item_read, run_read
from polycolab.conversations.routes.schemas import (
    ConversationCapabilities,
    ConversationCreate,
    ConversationEvent,
    ConversationInterrupt,
    ConversationMessage,
    ConversationPatch,
    ConversationRead,
    EventAccepted,
    InterruptAccepted,
    ItemPage,
    MessageAccepted,
    MessageItemRead,
    RunRead,
    RunResume,
    SharingPatch,
    SharingRead,
)
from polycolab.conversations.service import (
    ConversationStateError,
    children,
    require_interrupt,
    require_read,
    require_submit,
    set_sharing,
)
from polycolab.db.converters.conversation import conversation_item
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlConversation,
    SqlConversationItem,
    SqlPlatformAgentVersion,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.conversation import (
    Conversation,
    ConversationExecution,
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
    safe_failure_code,
)
from polycolab.entities.enums import AgentRunStatus
from polycolab.entities.time import utc_now
from polycolab.execution.limits import ExecutionLimits, enforce_sse_reconnect_limit
from polycolab.platform.observability import metrics

router = APIRouter(prefix="/api/v1")
_TERMINAL = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.FAILED,
    AgentRunStatus.TIMED_OUT,
}


def _execution_limits(request: Request) -> ExecutionLimits:
    settings = request.app.state.settings
    return ExecutionLimits(
        user_requests_per_minute=settings.execution_user_requests_per_minute,
        project_requests_per_minute=settings.execution_project_requests_per_minute,
        user_concurrent_runs=settings.execution_user_concurrent_runs,
        project_concurrent_runs=settings.execution_project_concurrent_runs,
        user_daily_tokens=settings.execution_user_daily_tokens,
        project_daily_tokens=settings.execution_project_daily_tokens,
        user_daily_cost_microusd=settings.execution_user_daily_cost_microusd,
        project_daily_cost_microusd=settings.execution_project_daily_cost_microusd,
        input_microusd_per_million_tokens=settings.gateway_input_microusd_per_million_tokens,
        output_microusd_per_million_tokens=settings.gateway_output_microusd_per_million_tokens,
        max_run_output_tokens=settings.gateway_max_output_tokens,
        max_input_tokens_per_round=settings.execution_max_input_tokens_per_round,
        max_model_rounds=settings.runtime_max_model_rounds,
        max_attempts=settings.runtime_max_attempts,
    )


def _codex_spec(request: Request) -> dict[str, object] | None:
    from polycolab.agents.runtime.spec import RuntimeSpec
    from polycolab.execution.contracts import ResourceLimits

    settings = request.app.state.settings
    if settings.runtime_codex_image is None:
        return None  # The built-in executor runs without a hosted image.
    return RuntimeSpec(
        image=settings.runtime_codex_image,
        sandbox_backend=settings.runtime_sandbox_backend,
        sandbox_version=settings.runtime_sandbox_version,
        max_model_requests=settings.runtime_max_model_rounds,
        max_attempts=settings.runtime_max_attempts,
        max_output_tokens=settings.gateway_max_output_tokens,
        max_input_bytes=min(settings.gateway_max_input_bytes, 262_144),
        max_input_tokens=settings.execution_max_input_tokens_per_round,
        input_microusd_per_million_tokens=settings.gateway_input_microusd_per_million_tokens,
        output_microusd_per_million_tokens=settings.gateway_output_microusd_per_million_tokens,
        limits=ResourceLimits(
            cpu_count=1,
            cpu_seconds=settings.runtime_run_timeout_seconds,
            wall_seconds=settings.runtime_run_timeout_seconds,
            memory_bytes=1024**3,
            process_count=64,
            disk_bytes=4 * 1024**3,
            output_bytes=16 * 1024**2,
            log_bytes=1024**2,
            output_files=64,
        ),
    ).model_dump(mode="json")


def _agent_execution_enabled(request: Request) -> None:
    if not request.app.state.settings.feature_agent_execution_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if request.app.state.settings.runtime_codex_image:
        from polycolab.agents.routes.capabilities import hosted_ready

        with request.app.state.session_factory() as session:
            if not hosted_ready(session, request.app.state.settings):
                raise HTTPException(status_code=503, detail="hosted_executor_unavailable")


def _consume_sse_reconnect(
    db: DbSession, *, request: Request, user_id: UUID, is_reconnect: bool
) -> None:
    if not is_reconnect:
        return
    try:
        enforce_sse_reconnect_limit(
            db,
            user_id=user_id,
            limit=request.app.state.settings.sse_reconnects_per_minute,
            now=utc_now(),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.get(
    "/platform-agents",
    response_model=list[PlatformAgentRead],
    operation_id="listPlatformAgents",
    tags=["agents"],
)
def list_platform_agents(
    response: Response, page: Page, db: DbSession, _user: CurrentUser
) -> list[PlatformAgentRead]:
    ensure_platform_agent_versions(db)
    values = [
        PlatformAgentRead.model_validate(value)
        for value in db.scalars(
            select(SqlPlatformAgentVersion)
            .where(SqlPlatformAgentVersion.version == 3)
            .order_by(SqlPlatformAgentVersion.agent_kind, SqlPlatformAgentVersion.version)
        )
    ]
    return paginated(values, page, response)


def _encode_cursor(values: list[object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(["v1", *values]).encode()).decode()


def _decode_cursor(value: str | None) -> list[object] | None:
    if value is None:
        return None
    try:
        result = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(result, list) or not result or result[0] != "v1":
            raise ValueError
        return result[1:]
    except ValueError, binascii.Error, UnicodeError:
        raise HTTPException(422, "invalid_cursor") from None


def _sequence_cursor(value: str | None) -> int:
    parts = _decode_cursor(value)
    if parts is None:
        return 0
    if len(parts) != 1 or type(parts[0]) is not int or not 0 <= parts[0] < 2**63:
        raise HTTPException(422, "invalid_cursor")
    return parts[0]


def _activity_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    parts = _decode_cursor(value)
    if parts is None:
        return None
    try:
        if len(parts) != 2 or not isinstance(parts[0], str) or not isinstance(parts[1], str):
            raise ValueError
        timestamp = datetime.fromisoformat(parts[0])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp, UUID(parts[1])
    except ValueError:
        raise HTTPException(422, "invalid_cursor") from None


def _capabilities(
    db: DbSession,
    value: Conversation,
    user_id: UUID,
    project_rights: dict[UUID, bool] | None = None,
) -> ConversationCapabilities:
    rights = project_rights if project_rights is not None else {}
    project_can_run = False
    if value.project_id is not None:
        if value.project_id not in rights:
            rights[value.project_id] = project_policy.can(
                SqlAlchemyTransaction(db), value.project_id, user_id, ProjectAction.RUN_AGENTS
            )
        project_can_run = rights[value.project_id]
    agent = value.origin is ConversationOrigin.AGENT
    owner = value.owner_id == user_id
    return ConversationCapabilities(
        can_send=(
            agent
            and value.status is ConversationStatus.ACTIVE
            and project_can_run
            and (owner or value.sharing is ConversationSharing.MEMBERS_CAN_PARTICIPATE)
            and value.configuration is not None
            and value.configuration.harness in {"platform", "codex"}
        ),
        can_manage=owner,
        can_share=owner and agent and value.project_id is not None,
        can_stream=agent,
    )


def _read_conversation(db: DbSession, value: Conversation, user_id: UUID) -> ConversationRead:
    latest = SqlAlchemyTransaction(db).conversations.latest_executions([value.id]).get(value.id)
    return conversation_read(
        value,
        viewer_id=user_id,
        capabilities=_capabilities(db, value, user_id),
        latest_execution=latest,
    )


def _read_conversations(
    db: DbSession, values: list[Conversation], user_id: UUID
) -> list[ConversationRead]:
    latest = SqlAlchemyTransaction(db).conversations.latest_executions(
        [value.id for value in values]
    )
    rights: dict[UUID, bool] = {}
    return [
        conversation_read(
            value,
            viewer_id=user_id,
            capabilities=_capabilities(db, value, user_id, rights),
            latest_execution=latest.get(value.id),
        )
        for value in values
    ]


def _execution(
    db: DbSession, run_id: UUID, user_id: UUID
) -> tuple[Conversation, ConversationExecution]:
    transaction = SqlAlchemyTransaction(db)
    execution = transaction.conversations.execution(run_id)
    if execution is None:
        raise ProjectNotFound
    parent = require_read(transaction, execution.conversation_id, user_id)
    if execution.project_id != parent.project_id:
        raise ProjectNotFound
    return parent, execution


def _read_run(db: DbSession, run_id: UUID, user_id: UUID) -> RunRead:
    parent, value = _execution(db, run_id, user_id)
    return run_read(
        value,
        viewer_id=user_id,
        owner_id=parent.owner_id,
        can_send=_capabilities(db, parent, user_id).can_send,
    )


@router.post(
    "/conversations",
    response_model=ConversationRead,
    status_code=201,
    operation_id="createConversation",
    tags=["conversations"],
)
def create(
    payload: ConversationCreate, request: Request, db: DbSession, user: CurrentUser
) -> ConversationRead:
    _agent_execution_enabled(request)
    if payload.harness == "codex" and request.app.state.settings.runtime_codex_image is None:
        raise HTTPException(409, "hosted_harness_unavailable")
    value = create_agent_conversation(
        db,
        project_id=payload.project_id,
        created_by_user_id=user.id,
        agent_kind=payload.agent_kind,
        title=payload.title,
        version=payload.agent_version,
        harness=payload.harness,
        system_prompt=payload.system_prompt,
        worktree_id=payload.worktree_id,
    )
    return _read_conversation(
        db, require_read(SqlAlchemyTransaction(db), value.id, user.id), user.id
    )


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    operation_id="listConversations",
    tags=["conversations"],
)
def list_conversations(
    response: Response,
    db: DbSession,
    user: CurrentUser,
    project_id: UUID | None = None,
    archived: bool | None = None,
    origin: ConversationOrigin | None = None,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[ConversationRead]:
    transaction = SqlAlchemyTransaction(db)
    if project_id is not None:
        project_policy.require_scope(transaction, project_id, user.id, ProjectAction.VIEW)
    values = transaction.conversations.list_accessible(
        user.id,
        project_id=project_id,
        origin=origin,
        archived=archived,
        after=_activity_cursor(cursor),
        limit=limit + 1,
    )
    if len(values) > limit:
        last = values[limit - 1]
        response.headers["X-Next-Cursor"] = _encode_cursor(
            [last.updated_at.isoformat(), str(last.id)]
        )
    return _read_conversations(db, values[:limit], user.id)


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    operation_id="getConversation",
    tags=["conversations"],
)
def get_conversation(conversation_id: UUID, db: DbSession, user: CurrentUser) -> ConversationRead:
    return _read_conversation(
        db, require_read(SqlAlchemyTransaction(db), conversation_id, user.id), user.id
    )


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationRead,
    operation_id="updateConversation",
    tags=["conversations"],
)
def patch_conversation(
    conversation_id: UUID, payload: ConversationPatch, db: DbSession, user: CurrentUser
) -> ConversationRead:
    value = update_conversation_metadata(
        db,
        conversation_id=conversation_id,
        user_id=user.id,
        title=payload.title,
        change_title="title" in payload.model_fields_set,
        archived=payload.archived,
    )
    return _read_conversation(db, value, user.id)


@router.get(
    "/conversations/{conversation_id}/items",
    response_model=ItemPage,
    operation_id="listConversationItems",
    tags=["conversations"],
)
def items(
    conversation_id: UUID,
    db: DbSession,
    user: CurrentUser,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=100, ge=1, le=100),
) -> ItemPage:
    transaction = SqlAlchemyTransaction(db)
    require_read(transaction, conversation_id, user.id)
    values = transaction.conversations.items(
        conversation_id, after=_sequence_cursor(cursor), limit=limit + 1
    )
    return ItemPage(
        items=[item_read(value) for value in values[:limit]],
        next_cursor=_encode_cursor([values[limit - 1].sequence]) if len(values) > limit else None,
    )


@router.get(
    "/conversations/{conversation_id}/child_conversations",
    response_model=list[ConversationRead],
    operation_id="listChildConversations",
    tags=["conversations"],
)
def child_conversations(
    conversation_id: UUID,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=25, ge=1, le=100),
) -> list[ConversationRead]:
    values = children(
        SqlAlchemyTransaction(db),
        conversation_id,
        user.id,
        after=_activity_cursor(cursor),
        limit=limit + 1,
    )
    if len(values) > limit:
        last = values[limit - 1]
        response.headers["X-Next-Cursor"] = _encode_cursor(
            [last.updated_at.isoformat(), str(last.id)]
        )
    return _read_conversations(db, values[:limit], user.id)


@router.get(
    "/conversations/{conversation_id}/sharing",
    response_model=SharingRead,
    operation_id="getConversationSharing",
    tags=["conversations"],
)
def get_sharing(conversation_id: UUID, db: DbSession, user: CurrentUser) -> SharingRead:
    value = require_read(SqlAlchemyTransaction(db), conversation_id, user.id)
    return SharingRead(
        mode=value.sharing,
        can_manage=value.owner_id == user.id and value.origin is ConversationOrigin.AGENT,
    )


@router.patch(
    "/conversations/{conversation_id}/sharing",
    response_model=SharingRead,
    operation_id="setConversationSharing",
    tags=["conversations"],
)
def patch_sharing(
    conversation_id: UUID, payload: SharingPatch, db: DbSession, user: CurrentUser
) -> SharingRead:
    value = set_sharing(SqlAlchemyTransaction(db), conversation_id, user.id, payload.mode)
    return SharingRead(mode=value.sharing, can_manage=value.origin is ConversationOrigin.AGENT)


@router.get(
    "/conversations/{conversation_id}/runs",
    response_model=list[RunRead],
    operation_id="listConversationRuns",
    tags=["conversations"],
)
def list_runs(
    conversation_id: UUID,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[RunRead]:
    transaction = SqlAlchemyTransaction(db)
    parent = require_read(transaction, conversation_id, user.id)
    values = transaction.conversations.executions(
        conversation_id, after=_sequence_cursor(cursor), limit=limit + 1
    )
    if len(values) > limit:
        response.headers["X-Next-Cursor"] = _encode_cursor([values[limit - 1].sequence])
    can_send = _capabilities(db, parent, user.id).can_send
    return [
        run_read(value, viewer_id=user.id, owner_id=parent.owner_id, can_send=can_send)
        for value in values[:limit]
    ]


@router.get("/runs/{run_id}", response_model=RunRead, operation_id="getRun", tags=["runs"])
def get_run(run_id: UUID, db: DbSession, user: CurrentUser) -> RunRead:
    return _read_run(db, run_id, user.id)


def _validate_context(
    db: DbSession,
    value: Conversation,
    user_id: UUID,
    artifact_ids: list[UUID],
) -> None:
    assert value.project_id is not None
    for artifact_id in artifact_ids:
        artifacts.read(db, project_id=value.project_id, user_id=user_id, artifact_id=artifact_id)


def _accepted_message(
    db: DbSession, message: SqlConversationItem, run: SqlAgentRun, user_id: UUID
) -> MessageAccepted:
    item = item_read(conversation_item(message))
    assert isinstance(item, MessageItemRead)
    # This is the immutable admission receipt. GET /runs/{id} supplies live state.
    current = _read_run(db, run.id, user_id)
    accepted = current.model_copy(
        update={
            "status": AgentRunStatus.QUEUED,
            "attempt": 0,
            "started_at": None,
            "finished_at": None,
            "failure_code": None,
            "cancel_requested_at": None,
            "observed_model": None,
            "usage": None,
            "updated_at": current.created_at,
            "can_interrupt": True,
            "can_resume": False,
        }
    )
    return MessageAccepted(item=item, run=accepted)


def _message(
    conversation_id: UUID,
    payload: ConversationMessage,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> MessageAccepted:
    value = require_read(SqlAlchemyTransaction(db), conversation_id, user.id)
    if value.origin is not ConversationOrigin.AGENT:
        raise ConversationStateError("legacy history is read-only")
    accepted = accepted_user_message(
        db,
        conversation_id=conversation_id,
        requested_by_user_id=user.id,
        provider_connection_id=payload.provider_connection_id,
        content_md=payload.content_md,
        context_artifact_ids=payload.context_artifact_ids,
        client_request_id=payload.client_request_id,
    )
    if accepted is not None:
        return _accepted_message(db, *accepted, user.id)
    value = require_submit(SqlAlchemyTransaction(db), conversation_id, user.id)
    _agent_execution_enabled(request)
    assert value.project_id is not None
    _validate_context(db, value, user.id, payload.context_artifact_ids)
    message, run = append_user_message_and_queue_run(
        db,
        conversation_id=value.id,
        requested_by_user_id=user.id,
        provider_connection_id=payload.provider_connection_id,
        content_md=payload.content_md,
        context_artifact_ids=payload.context_artifact_ids,
        client_request_id=payload.client_request_id,
        deadline_at=utc_now()
        + timedelta(seconds=request.app.state.settings.runtime_run_timeout_seconds),
        execution_limits=_execution_limits(request),
        runtime_spec=_codex_spec(request),
    )
    return _accepted_message(db, message, run, user.id)


@router.post(
    "/conversations/{conversation_id}/events",
    response_model=EventAccepted,
    status_code=202,
    operation_id="submitConversationEvent",
    tags=["conversations"],
)
def submit_event(
    conversation_id: UUID,
    payload: ConversationEvent,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> EventAccepted:
    if isinstance(payload, ConversationInterrupt):
        parent, execution = _execution(db, payload.run_id, user.id)
        if parent.id != conversation_id:
            raise ProjectNotFound
        require_interrupt(
            SqlAlchemyTransaction(db),
            conversation_id,
            user.id,
            requested_by_user_id=execution.requested_by_user_id,
        )
        request_cancel(db, run_id=execution.id)
        return InterruptAccepted(run=_read_run(db, execution.id, user.id))
    return _message(conversation_id, payload, request, db, user)


@router.post(
    "/runs/{run_id}/resume",
    response_model=RunRead,
    status_code=202,
    operation_id="resumeRun",
    tags=["runs"],
)
def resume(
    run_id: UUID, payload: RunResume, request: Request, db: DbSession, user: CurrentUser
) -> RunRead:
    parent, execution = _execution(db, run_id, user.id)
    require_submit(SqlAlchemyTransaction(db), parent.id, user.id)
    if execution.requested_by_user_id != user.id:
        raise AuthorizationDenied
    _agent_execution_enabled(request)
    assert execution.context is not None
    _validate_context(
        db,
        parent,
        user.id,
        list(execution.context.artifact_ids),
    )
    successor = resume_run(
        db,
        run_id=run_id,
        requested_by_user_id=user.id,
        provider_connection_id=payload.provider_connection_id,
        client_request_id=payload.client_request_id,
        deadline_at=utc_now()
        + timedelta(seconds=request.app.state.settings.runtime_run_timeout_seconds),
        execution_limits=_execution_limits(request),
        runtime_spec=_codex_spec(request),
    )
    return _read_run(db, successor.id, user.id)


def _conversation_participant(db: DbSession, *, value: SqlConversation, user_id: UUID) -> bool:
    try:
        require_read(SqlAlchemyTransaction(db), value.id, user_id)
    except AuthorizationDenied, ProjectNotFound:
        return False
    return True


def _event_bytes(event: SqlAgentRunEvent, event_id: str) -> bytes:
    # The same safe tool metadata is present in saved items and shared replay.
    allowed = {
        "ASSISTANT_DELTA": {"text"},
        "TOOL_REQUESTED": {"tool_name", "round"},
        "TOOL_RESULT": {"tool_name", "round", "outcome"},
        "RUN_STARTED": {"attempt"},
        "RUN_COMPLETED": {"message_id", "sequence"},
        "ASSISTANT_MESSAGE_COMPLETED": {"message_id", "sequence"},
        "USAGE_REPORTED": {"source", "input_tokens", "output_tokens", "total_tokens"},
    }.get(event.kind.value, {"code", "attempt"})
    data = AgentRunEventRead.model_validate(event).model_dump(mode="json")
    payload = {key: value for key, value in event.payload.items() if key in allowed}
    if "code" in payload and payload["code"] is not None:
        payload["code"] = (
            safe_failure_code(payload["code"])
            if isinstance(payload["code"], str)
            else "execution_failed"
        )
    data["payload"] = payload
    encoded = json.dumps(data, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event.kind.value.lower()}\ndata: {encoded}\n\n".encode()


def _last_conversation_cursor(value: str | None) -> tuple[int, int]:
    if value is None:
        return 0, 0
    try:
        run_sequence, event_cursor = (int(part) for part in value.split(":", maxsplit=1))
    except ValueError:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="malformed")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    if not 0 <= run_sequence < 2**63 or not 0 <= event_cursor < 2**63:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="negative")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    return run_sequence, event_cursor


async def _conversation_event_stream(
    request: Request, *, conversation_id: UUID, user_id: UUID, cursor: tuple[int, int]
) -> AsyncIterator[bytes]:
    heartbeat_at = time.monotonic()
    settings = request.app.state.settings
    metrics.adjust_gauge("polycolab_sse_connections", 1, service=settings.service_name)
    try:
        while not await request.is_disconnected():
            db = request.app.state.session_factory()
            try:
                conversation_value = db.get(SqlConversation, conversation_id)
                if conversation_value is None or not _conversation_participant(
                    db, value=conversation_value, user_id=user_id
                ):
                    return
                first_pending = db.scalar(
                    select(func.min(SqlAgentRun.queue_sequence)).where(
                        SqlAgentRun.conversation_id == conversation_id,
                        SqlAgentRun.status.not_in(_TERMINAL),
                    )
                )
                rows = list(
                    db.execute(
                        select(SqlAgentRun, SqlAgentRunEvent)
                        .join(SqlAgentRunEvent, SqlAgentRunEvent.run_id == SqlAgentRun.id)
                        .where(
                            SqlAgentRun.conversation_id == conversation_id,
                            SqlAgentRun.queue_sequence <= first_pending
                            if first_pending is not None
                            else true(),
                            or_(
                                SqlAgentRun.queue_sequence > cursor[0],
                                (SqlAgentRun.queue_sequence == cursor[0])
                                & (SqlAgentRunEvent.cursor > cursor[1]),
                            ),
                        )
                        .order_by(SqlAgentRun.queue_sequence, SqlAgentRunEvent.cursor)
                        .limit(settings.runtime_event_batch_size)
                    )
                )
                archived = conversation_value.archived_at is not None
                active_runs = db.scalar(
                    select(SqlAgentRun.id)
                    .where(
                        SqlAgentRun.conversation_id == conversation_id,
                        SqlAgentRun.status.not_in(_TERMINAL),
                    )
                    .limit(1)
                )
            finally:
                db.close()
            for run, event in rows:
                cursor = run.queue_sequence, event.cursor
                yield _event_bytes(event, f"{cursor[0]}:{cursor[1]}")
                heartbeat_at = time.monotonic()
            if archived and active_runs is None and not rows:
                return
            if time.monotonic() - heartbeat_at >= settings.runtime_sse_heartbeat_seconds:
                yield b": heartbeat\n\n"
                heartbeat_at = time.monotonic()
            await asyncio.sleep(settings.runtime_sse_poll_seconds)
    finally:
        metrics.adjust_gauge("polycolab_sse_connections", -1, service=settings.service_name)


@router.get(
    "/conversations/{conversation_id}/stream",
    response_class=StreamingResponse,
    operation_id="streamConversation",
    tags=["conversations"],
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_conversation(
    conversation_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    value = require_read(SqlAlchemyTransaction(db), conversation_id, user.id)
    if value.origin is not ConversationOrigin.AGENT:
        raise ConversationStateError("legacy history has no live execution stream")
    cursor = _last_conversation_cursor(last_event_id)
    _consume_sse_reconnect(
        db, request=request, user_id=user.id, is_reconnect=last_event_id is not None
    )
    if last_event_id is not None:
        metrics.increment("polycolab_sse_reconnects_total", outcome="conversation_cursor")
    return StreamingResponse(
        _conversation_event_stream(
            request, conversation_id=conversation_id, user_id=user.id, cursor=cursor
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

"""Public canonical session/run API and committed-event SSE delivery."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    project_policy,
)
from polycolab.agents.access import _run_scope as _run_scope
from polycolab.agents.access import _session_scope as _session_scope
from polycolab.agents.schemas import (
    AgentMessageCreate,
    AgentMessageRead,
    AgentRunEventRead,
    AgentRunRead,
    AgentRunResume,
    AgentRunSummary,
    AgentSessionCreate,
    AgentSessionRead,
    AgentTurnQueued,
    PlatformAgentRead,
)
from polycolab.agents.sessions import (
    SessionNotFound,
    SessionStateError,
    append_user_message_and_queue_run,
    archive_agent_session,
    create_agent_session,
    ensure_platform_agent_versions,
    request_cancel,
    resume_run,
)
from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.artifacts import service as artifacts
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentSession,
    SqlPlatformAgentVersion,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunStatus, ProjectRole
from polycolab.entities.time import utc_now
from polycolab.execution.limits import (
    ExecutionLimitExceeded,
    ExecutionLimits,
    enforce_sse_reconnect_limit,
)
from polycolab.platform.observability import metrics
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision

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
    from polycolab.verification.contracts import ResourceLimits

    settings = request.app.state.settings
    if settings.runtime_codex_image is None:
        return None  # Legacy admission during the disabled, pre-cutover period.
    return RuntimeSpec(
        image=settings.runtime_codex_image,
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


def _latest_runs(db: DbSession, session_ids: list[UUID]) -> dict[UUID, AgentRunSummary]:
    if not session_ids:
        return {}
    ranked = (
        select(
            SqlAgentRun.id,
            func.row_number()
            .over(
                partition_by=SqlAgentRun.session_id,
                order_by=(SqlAgentRun.queue_sequence.desc(), SqlAgentRun.id.desc()),
            )
            .label("position"),
        )
        .where(SqlAgentRun.session_id.in_(session_ids))
        .subquery()
    )
    return {
        run.session_id: AgentRunSummary.model_validate(run)
        for run in db.scalars(
            select(SqlAgentRun)
            .join(ranked, ranked.c.id == SqlAgentRun.id)
            .where(ranked.c.position == 1)
        )
    }


def _session_read(
    db: DbSession,
    value: SqlAgentSession,
    *,
    agents: dict[UUID, SqlPlatformAgentVersion] | None = None,
    latest_runs: dict[UUID, AgentRunSummary] | None = None,
) -> AgentSessionRead:
    agent = (
        db.get(SqlPlatformAgentVersion, value.agent_version_id)
        if agents is None
        else agents.get(value.agent_version_id)
    )
    if agent is None:
        raise SessionNotFound
    return AgentSessionRead(
        id=value.id,
        task_id=value.task_id,
        worktree_id=value.task_id,
        project_id=value.project_id,
        agent_version_id=agent.id,
        agent_kind=agent.agent_kind,
        agent_version=agent.version,
        agent_display_name=agent.display_name,
        harness=value.harness,
        system_prompt=value.system_prompt,
        created_by_user_id=value.created_by_user_id,
        title=value.title,
        status=value.status,
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        latest_run=(latest_runs if latest_runs is not None else _latest_runs(db, [value.id])).get(
            value.id
        ),
    )


def _session_participant(db: DbSession, *, value: SqlAgentSession, user_id: UUID) -> bool:
    """Return whether this current member may access this private chat history."""

    membership = project_policy.membership(SqlAlchemyTransaction(db), value.project_id, user_id)
    return (
        membership is not None
        and membership.role is not ProjectRole.READ_ONLY
        and value.created_by_user_id == user_id
        and project_policy.can(
            SqlAlchemyTransaction(db), value.project_id, user_id, ProjectAction.VIEW
        )
    )


def _run_read(run: SqlAgentRun) -> AgentRunRead:
    return AgentRunRead.model_validate(run)


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
            .where(SqlPlatformAgentVersion.version <= 2)
            .order_by(SqlPlatformAgentVersion.agent_kind, SqlPlatformAgentVersion.version)
        )
    ]
    return paginated(values, page, response)


@router.post(
    "/agent-sessions",
    response_model=AgentSessionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createAgentSession",
    tags=["agent-sessions"],
)
def post_agent_session(
    payload: AgentSessionCreate, request: Request, db: DbSession, user: CurrentUser
) -> AgentSessionRead:
    _agent_execution_enabled(request)
    if payload.harness == "codex" and request.app.state.settings.runtime_codex_image is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="hosted_harness_unavailable"
        )
    project_policy.require_scope(
        SqlAlchemyTransaction(db), payload.project_id, user.id, ProjectAction.RUN_AGENTS
    )
    value = create_agent_session(
        db,
        project_id=payload.project_id,
        created_by_user_id=user.id,
        agent_kind=payload.agent_kind,
        title=payload.title,
        version=payload.agent_version,
        harness=payload.harness,
        system_prompt=payload.system_prompt,
        task_id=payload.task_id,
    )
    return _session_read(db, value)


@router.get(
    "/agent-sessions",
    response_model=list[AgentSessionRead],
    operation_id="listAgentSessions",
    tags=["agent-sessions"],
)
def list_agent_sessions(
    project_id: UUID,
    response: Response,
    page: Page,
    db: DbSession,
    user: CurrentUser,
) -> list[AgentSessionRead]:
    scope = project_policy.require_scope(
        SqlAlchemyTransaction(db), project_id, user.id, ProjectAction.VIEW
    )
    if scope.membership.role is ProjectRole.READ_ONLY:
        raise AuthorizationDenied
    values = list(
        db.scalars(
            select(SqlAgentSession)
            .where(
                SqlAgentSession.project_id == project_id,
                SqlAgentSession.created_by_user_id == user.id,
            )
            .order_by(SqlAgentSession.updated_at.desc(), SqlAgentSession.id.desc())
        )
    )
    selected = paginated(values, page, response)
    agents = {
        agent.id: agent
        for agent in db.scalars(
            select(SqlPlatformAgentVersion).where(
                SqlPlatformAgentVersion.id.in_({value.agent_version_id for value in selected})
            )
        )
    }
    latest_runs = _latest_runs(db, [value.id for value in selected])
    return [_session_read(db, value, agents=agents, latest_runs=latest_runs) for value in selected]


@router.get(
    "/agent-sessions/{session_id}",
    response_model=AgentSessionRead,
    operation_id="getAgentSession",
    tags=["agent-sessions"],
)
def get_agent_session(session_id: UUID, db: DbSession, user: CurrentUser) -> AgentSessionRead:
    return _session_read(
        db,
        _session_scope(db, session_id=session_id, user_id=user.id, action=ProjectAction.VIEW),
    )


@router.get(
    "/agent-sessions/{session_id}/runs",
    response_model=list[AgentRunRead],
    operation_id="listAgentSessionRuns",
    tags=["agent-sessions"],
)
def list_agent_session_runs(
    session_id: UUID, response: Response, page: Page, db: DbSession, user: CurrentUser
) -> list[AgentRunRead]:
    _session_scope(db, session_id=session_id, user_id=user.id, action=ProjectAction.VIEW)
    # Ascending immutable queue order keeps offset cursors stable as new turns arrive.
    values = list(
        db.scalars(
            select(SqlAgentRun)
            .where(SqlAgentRun.session_id == session_id)
            .order_by(SqlAgentRun.queue_sequence, SqlAgentRun.id)
            .offset(page.offset)
            .limit(page.limit + 1)
        )
    )
    if len(values) > page.limit:
        response.headers["X-Next-Cursor"] = base64.urlsafe_b64encode(
            f"v1:{page.offset + page.limit}".encode("ascii")
        ).decode("ascii")
    return [AgentRunRead.model_validate(value) for value in values[: page.limit]]


@router.post(
    "/agent-sessions/{session_id}/archive",
    response_model=AgentSessionRead,
    operation_id="archiveAgentSession",
    tags=["agent-sessions"],
)
def post_agent_session_archive(
    session_id: UUID, db: DbSession, user: CurrentUser
) -> AgentSessionRead:
    value = _session_scope(
        db, session_id=session_id, user_id=user.id, action=ProjectAction.RUN_AGENTS
    )
    return _session_read(db, archive_agent_session(db, session_id=value.id))


@router.get(
    "/agent-sessions/{session_id}/messages",
    response_model=list[AgentMessageRead],
    operation_id="listAgentSessionMessages",
    tags=["agent-sessions"],
)
def list_agent_session_messages(
    session_id: UUID,
    response: Response,
    page: Page,
    db: DbSession,
    user: CurrentUser,
) -> list[AgentMessageRead]:
    _session_scope(db, session_id=session_id, user_id=user.id, action=ProjectAction.VIEW)
    values = [
        AgentMessageRead.model_validate(value)
        for value in db.scalars(
            select(SqlAgentMessage)
            .where(SqlAgentMessage.session_id == session_id)
            .order_by(SqlAgentMessage.sequence)
        )
    ]
    return paginated(values, page, response)


@router.post(
    "/agent-sessions/{session_id}/messages",
    response_model=AgentTurnQueued,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="queueAgentSessionTurn",
    tags=["agent-sessions"],
)
def post_agent_session_message(
    session_id: UUID,
    payload: AgentMessageCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> AgentTurnQueued:
    _agent_execution_enabled(request)
    value = _session_scope(
        db, session_id=session_id, user_id=user.id, action=ProjectAction.RUN_AGENTS
    )
    if payload.requested_authority is not None:
        operations = set(payload.requested_authority.allowed_operations)
        if (
            "RUN_VERIFICATION" in operations
            and not request.app.state.settings.feature_verification_submission_enabled
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    try:
        for revision_id in payload.context_object_version_ids:
            accessible_revision(db, revision_id, value.project_id)
        for artifact_id in payload.context_artifact_ids:
            artifacts.read(
                db,
                project_id=value.project_id,
                user_id=user.id,
                artifact_id=artifact_id,
            )
    except ResearchNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    from polycolab.db.stores.repositories import SqlRepositoryStore
    from polycolab.entities.repositories import RepositoryError

    binding = SqlRepositoryStore(db).session(value.project_id, value.id)
    if (
        binding.enabled
        and payload.requested_authority is not None
        and payload.requested_authority.destination == "PUBLIC"
    ):
        raise RepositoryError("repository_public_run_denied", 403)
    deadline = utc_now() + timedelta(seconds=request.app.state.settings.runtime_run_timeout_seconds)
    try:
        message, run = append_user_message_and_queue_run(
            db,
            session_id=value.id,
            requested_by_user_id=user.id,
            gateway_profile_id=payload.gateway_profile_id,
            content_md=payload.content_md,
            context_revision_ids=payload.context_object_version_ids,
            context_artifact_ids=payload.context_artifact_ids,
            requested_authority=payload.requested_authority.historical_command()
            if payload.requested_authority is not None
            else None,
            client_request_id=payload.client_request_id,
            deadline_at=deadline,
            execution_limits=_execution_limits(request),
            runtime_spec=_codex_spec(request),
        )
    except ExecutionLimitExceeded:
        raise
    except SessionStateError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from None
    return AgentTurnQueued(message=AgentMessageRead.model_validate(message), run=_run_read(run))


@router.get(
    "/agent-runs/{run_id}",
    response_model=AgentRunRead,
    operation_id="getAgentRun",
    tags=["agent-runs"],
)
def get_agent_run(run_id: UUID, db: DbSession, user: CurrentUser) -> AgentRunRead:
    return _run_read(_run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.VIEW))


@router.post(
    "/agent-runs/{run_id}/cancel",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="cancelAgentRun",
    tags=["agent-runs"],
)
def post_agent_run_cancel(run_id: UUID, db: DbSession, user: CurrentUser) -> AgentRunRead:
    run = _run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.RUN_AGENTS)
    return _run_read(request_cancel(db, run_id=run.id))


@router.post(
    "/agent-runs/{run_id}/resume",
    response_model=AgentRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="resumeAgentRun",
    tags=["agent-runs"],
)
def post_agent_run_resume(
    run_id: UUID, payload: AgentRunResume, request: Request, db: DbSession, user: CurrentUser
) -> AgentRunRead:
    _agent_execution_enabled(request)
    run = _run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.RUN_AGENTS)
    deadline = utc_now() + timedelta(seconds=request.app.state.settings.runtime_run_timeout_seconds)
    try:
        successor = resume_run(
            db,
            run_id=run.id,
            requested_by_user_id=user.id,
            gateway_profile_id=payload.gateway_profile_id,
            client_request_id=payload.client_request_id,
            deadline_at=deadline,
            execution_limits=_execution_limits(request),
            runtime_spec=_codex_spec(request),
        )
    except ExecutionLimitExceeded:
        raise
    except SessionStateError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT) from None
    return _run_read(successor)


def _last_run_cursor(value: str | None, after: int) -> int:
    if value is None:
        return after
    try:
        parsed = int(value)
    except ValueError:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="malformed")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    if parsed < 0:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="negative")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if parsed < after:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="regressive")
        return after
    return parsed


def _event_bytes(event: SqlAgentRunEvent, event_id: str) -> bytes:
    data = AgentRunEventRead.model_validate(event).model_dump(mode="json")
    encoded = json.dumps(data, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event.kind.value.lower()}\ndata: {encoded}\n\n".encode()


async def _run_event_stream(
    request: Request, *, run_id: UUID, user_id: UUID, cursor: int
) -> AsyncIterator[bytes]:
    heartbeat_at = time.monotonic()
    settings = request.app.state.settings
    metrics.adjust_gauge("polycolab_sse_connections", 1, service=settings.service_name)
    try:
        while not await request.is_disconnected():
            db = request.app.state.session_factory()
            try:
                run = db.get(SqlAgentRun, run_id)
                parent = db.get(SqlAgentSession, run.session_id) if run is not None else None
                if (
                    run is None
                    or parent is None
                    or run.requested_by_user_id != user_id
                    or not _session_participant(db, value=parent, user_id=user_id)
                ):
                    return
                events = list(
                    db.scalars(
                        select(SqlAgentRunEvent)
                        .where(SqlAgentRunEvent.run_id == run.id, SqlAgentRunEvent.cursor > cursor)
                        .order_by(SqlAgentRunEvent.cursor)
                        .limit(settings.runtime_event_batch_size)
                    )
                )
                terminal = run.status in _TERMINAL
            finally:
                db.close()
            for event in events:
                cursor = event.cursor
                yield _event_bytes(event, str(event.cursor))
                heartbeat_at = time.monotonic()
            if terminal and not events:
                return
            if time.monotonic() - heartbeat_at >= settings.runtime_sse_heartbeat_seconds:
                yield b": heartbeat\n\n"
                heartbeat_at = time.monotonic()
            await asyncio.sleep(settings.runtime_sse_poll_seconds)
    finally:
        metrics.adjust_gauge("polycolab_sse_connections", -1, service=settings.service_name)


@router.get(
    "/agent-runs/{run_id}/events",
    response_class=StreamingResponse,
    operation_id="streamAgentRunEvents",
    tags=["agent-runs"],
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_agent_run_events(
    run_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    _run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.VIEW)
    cursor = _last_run_cursor(last_event_id, after)
    _consume_sse_reconnect(
        db,
        request=request,
        user_id=user.id,
        is_reconnect=last_event_id is not None or after > 0,
    )
    if last_event_id is not None:
        metrics.increment("polycolab_sse_reconnects_total", outcome="run_cursor")
    return StreamingResponse(
        _run_event_stream(request, run_id=run_id, user_id=user.id, cursor=cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _last_session_cursor(value: str | None) -> tuple[int, int]:
    if value is None:
        return 0, 0
    try:
        run_sequence, event_cursor = (int(part) for part in value.split(":", maxsplit=1))
    except ValueError:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="malformed")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    if run_sequence < 0 or event_cursor < 0:
        metrics.increment("polycolab_sse_cursor_anomalies_total", anomaly="negative")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    return run_sequence, event_cursor


async def _session_event_stream(
    request: Request, *, session_id: UUID, user_id: UUID, cursor: tuple[int, int]
) -> AsyncIterator[bytes]:
    heartbeat_at = time.monotonic()
    settings = request.app.state.settings
    metrics.adjust_gauge("polycolab_sse_connections", 1, service=settings.service_name)
    try:
        while not await request.is_disconnected():
            db = request.app.state.session_factory()
            try:
                session_value = db.get(SqlAgentSession, session_id)
                if session_value is None or not _session_participant(
                    db, value=session_value, user_id=user_id
                ):
                    return
                rows = list(
                    db.execute(
                        select(SqlAgentRun, SqlAgentRunEvent)
                        .join(SqlAgentRunEvent, SqlAgentRunEvent.run_id == SqlAgentRun.id)
                        .where(
                            SqlAgentRun.session_id == session_id,
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
                archived = session_value.archived_at is not None
                active_runs = db.scalar(
                    select(SqlAgentRun.id)
                    .where(
                        SqlAgentRun.session_id == session_id, SqlAgentRun.status.not_in(_TERMINAL)
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
    "/agent-sessions/{session_id}/events",
    response_class=StreamingResponse,
    operation_id="streamAgentSessionEvents",
    tags=["agent-sessions"],
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_agent_session_events(
    session_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    value = _session_scope(db, session_id=session_id, user_id=user.id, action=ProjectAction.VIEW)
    cursor = _last_session_cursor(last_event_id)
    _consume_sse_reconnect(
        db,
        request=request,
        user_id=user.id,
        is_reconnect=last_event_id is not None,
    )
    if last_event_id is not None:
        metrics.increment("polycolab_sse_reconnects_total", outcome="session_cursor")
    return StreamingResponse(
        _session_event_stream(
            request,
            session_id=value.id,
            user_id=user.id,
            cursor=cursor,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

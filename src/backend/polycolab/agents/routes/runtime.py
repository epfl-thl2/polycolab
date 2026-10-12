"""Private authenticated state boundary for stateless agent-runtime workers."""

from __future__ import annotations

import secrets
from datetime import UTC, timedelta
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import WorkspaceAction, workspace_policy
from polycolab.accounts.authentication import AuthenticationRequired, bearer_token
from polycolab.agents.context import ContextInvalid, manifest_for_run
from polycolab.agents.runtime.errors import RuntimeApiConflict as RuntimeApiConflict
from polycolab.agents.sessions import (
    IdempotencyConflict,
    LeaseLost,
    SessionNotFound,
    activate_runtime_session_binding,
    append_worker_event,
    claim_next_run,
    create_runtime_run_binding,
    finish_run,
    record_usage,
    renew_lease,
    requeue_expired_runs,
    start_claimed_run,
)
from polycolab.agents.tools import ToolCapabilityInvalid, issue_tool_capability
from polycolab.db.models import SqlAgentRun, SqlRuntimeSessionBinding
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    AgentRunEventKind,
    AgentRunStatus,
    RuntimeBindingStatus,
    UsageSource,
)
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.execution.limits import (
    ExecutionLimitExceeded,
    ExecutionLimits,
    enforce_next_round_budget,
    purge_expired_rate_windows,
)
from polycolab.model_gateway.service import GrantInvalid, issue_run_grant
from polycolab.platform.observability import metrics

router = APIRouter(prefix="/internal/v1/runtime", include_in_schema=False)
logger = structlog.get_logger(__name__)


class RuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=200)
    engine: Literal["builtin", "codex"] = "builtin"
    incarnation: str | None = Field(default=None, max_length=36)
    slot_id: int | None = Field(default=None, ge=0, le=63)
    protocol_version: int = 4


class LeaseRequest(RuntimeRequest):
    lease_generation: int = Field(ge=1)


class EventRequest(LeaseRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    kind: Literal["ASSISTANT_DELTA", "TOOL_REQUESTED", "TOOL_RESULT"]
    payload: dict[str, object]


class UsageRequest(LeaseRequest):
    idempotency_key: str = Field(min_length=1, max_length=200)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class FinishRequest(LeaseRequest):
    status: Literal["COMPLETED", "CANCELLED", "FAILED", "TIMED_OUT"]
    failure_code: str | None = Field(default=None, max_length=100)
    final_message_md: str | None = Field(default=None, max_length=200_000)


def _record_authentication(outcome: str, credential_slot: str | None = None) -> None:
    metrics.increment("polycolab_runtime_worker_auth_total", outcome=outcome)
    # Current-credential success is represented by the metric but intentionally
    # not logged on every poll/event. Rotation overlap and failures are security
    # events worth retaining without producing an unbounded steady-state log.
    if outcome == "accepted_current":
        return
    log = logger.info if outcome.startswith("accepted_") else logger.warning
    log(
        "runtime_worker_authentication",
        outcome=outcome,
        credential_slot=credential_slot,
        security_event=True,
    )


def _authorize_worker(request: Request) -> None:
    token = bearer_token(request.headers.get("authorization"))
    settings = request.app.state.settings
    if token is None:
        _record_authentication("missing")
        raise AuthenticationRequired
    if secrets.compare_digest(token, settings.runtime_worker_secret):
        _record_authentication("accepted_current", "current")
        return
    previous = settings.runtime_worker_previous_token
    if previous is not None and secrets.compare_digest(token, previous.get_secret_value()):
        expires_at = settings.runtime_worker_previous_token_expires_at
        if expires_at is not None:
            normalized_expiry = (
                expires_at.replace(tzinfo=UTC)
                if expires_at.tzinfo is None
                else expires_at.astimezone(UTC)
            )
            if normalized_expiry > utc_now():
                _record_authentication("accepted_previous", "previous")
                return
        _record_authentication("expired_previous", "previous")
        raise AuthenticationRequired
    _record_authentication("invalid")
    raise AuthenticationRequired


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


def _messages(session: Session, run: SqlAgentRun) -> list[dict[str, object]]:
    from polycolab.agents.runtime.messages import model_messages

    return model_messages(session, run)


def _ensure_binding(session: Session, run: SqlAgentRun) -> None:
    binding = session.scalar(
        select(SqlRuntimeSessionBinding).where(
            SqlRuntimeSessionBinding.session_id == run.session_id,
            SqlRuntimeSessionBinding.status == RuntimeBindingStatus.ACTIVE,
        )
    )
    if binding is None:
        binding = activate_runtime_session_binding(
            session,
            session_id=run.session_id,
            adapter_name="codex" if run.runtime_spec else "builtin",
        )
    from polycolab.db.models import SqlRuntimeRunBinding

    run_binding = session.scalar(
        select(SqlRuntimeRunBinding.id).where(SqlRuntimeRunBinding.run_id == run.id)
    )
    if run_binding is None:
        create_runtime_run_binding(
            session,
            run_id=run.id,
            session_binding_id=binding.id,
            adapter_name="builtin",
        )


def _finish_claim_failure(session: Session, run: SqlAgentRun, worker_id: str, code: str) -> None:
    try:
        finish_run(
            session,
            run_id=run.id,
            worker_id=worker_id,
            lease_generation=run.lease_generation,
            status=AgentRunStatus.FAILED,
            failure_code=code,
        )
    except LeaseLost:
        session.rollback()


@router.post("/claims", response_model=None)
def claim_work(payload: RuntimeRequest, request: Request) -> Response | dict[str, object]:
    _authorize_worker(request)
    if payload.engine == "codex" and payload.protocol_version != 4:
        raise RuntimeApiConflict("executor_protocol_mismatch")
    settings = request.app.state.settings
    session = request.app.state.session_factory()
    try:
        purge_expired_rate_windows(
            session,
            retention=timedelta(minutes=settings.execution_rate_window_retention_minutes),
            now=utc_now(),
        )
        from polycolab.model_gateway.hosted import recover_pending

        recover_pending(session)
        from polycolab.agents.recovery import reconcile

        reconcile(session)
        requeue_expired_runs(session, max_attempts=settings.runtime_max_attempts)
        if payload.engine == "codex":
            from polycolab.db.models import SqlHostedExecutor
            from polycolab.execution.allocator import claim

            if settings.runtime_codex_image is not None:
                executor = session.get(SqlHostedExecutor, payload.worker_id)
                from polycolab.execution.allocator import utc

                if (
                    executor is None
                    or payload.incarnation != executor.incarnation
                    or payload.protocol_version != 4
                    or payload.slot_id is None
                    or utc(executor.expires_at) <= utc_now()
                    or executor.image_digest
                    != settings.runtime_codex_image.rsplit("@sha256:", 1)[-1]
                ):
                    raise RuntimeApiConflict("executor_not_ready")

            run = claim(
                session,
                worker_id=payload.worker_id,
                lease_seconds=settings.runtime_lease_seconds,
                capacity=settings.hosted_agent_capacity,
                slot_id=payload.slot_id,
                incarnation=payload.incarnation,
                image_digest=(
                    settings.runtime_codex_image.rsplit("@sha256:", 1)[-1]
                    if settings.runtime_codex_image is not None
                    else None
                ),
                user_capacity=min(
                    settings.hosted_agent_user_capacity, max(1, settings.hosted_agent_capacity - 1)
                ),
                workspace_capacity=min(
                    settings.hosted_agent_workspace_capacity,
                    max(1, settings.hosted_agent_capacity - 1),
                ),
            )
        else:
            run = claim_next_run(
                session,
                worker_id=payload.worker_id,
                lease_for=timedelta(seconds=settings.runtime_lease_seconds),
                engine=payload.engine,
            )
        if run is None:
            metrics.increment("polycolab_runtime_claims_total", outcome="empty")
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        try:
            run = start_claimed_run(
                session,
                run_id=run.id,
                worker_id=payload.worker_id,
                lease_generation=run.lease_generation,
            )
            _ensure_binding(session, run)
            if not workspace_policy.can(
                SqlAlchemyTransaction(session),
                run.project_id,
                run.requested_by_user_id,
                WorkspaceAction.RUN_AGENTS,
            ):
                _finish_claim_failure(session, run, payload.worker_id, "authorization_revoked")
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            from polycolab.db.stores.repositories import SqlRepositoryStore

            repository_enabled = (
                SqlRepositoryStore(session).session(run.project_id, run.session_id).enabled
            )
            if repository_enabled and (
                settings.workspace_repository_directory is None or payload.engine != "codex"
            ):
                raise RepositoryError("repository_unavailable", 503)
            manifest = manifest_for_run(session, run=run)
            capability = issue_tool_capability(
                session,
                run=run,
                manifest=manifest,
                ttl_seconds=settings.gateway_run_token_ttl_seconds,
                lease_generation=run.lease_generation,
            )
            envelope = {
                "run_id": str(run.id),
                "lease_generation": run.lease_generation,
                "model_id": run.gateway_model_id,
                "messages": _messages(session, run),
                "tool_capability": capability,
                "max_output_tokens": settings.gateway_max_output_tokens,
                "max_model_rounds": settings.runtime_max_model_rounds,
                "max_tool_calls": 16,
                "max_tool_argument_bytes": 65_536,
                "max_tool_result_bytes": 262_144,
                "lease_seconds": settings.runtime_lease_seconds,
                "deadline_at": run.deadline_at.isoformat() if run.deadline_at else None,
                "runtime_spec": run.runtime_spec,
            }
            if payload.engine == "codex":
                from polycolab.agents.runtime.spec import RuntimeSpec
                from polycolab.agents.tools import definitions

                if run.runtime_spec is None:
                    _finish_claim_failure(session, run, payload.worker_id, "runtime_spec_missing")
                    return Response(status_code=status.HTTP_204_NO_CONTENT)
                RuntimeSpec.model_validate(run.runtime_spec)
                if settings.workspace_repository_directory is not None:
                    from polycolab.workspaces.routes.repository import service as repository_service

                    envelope["repository"] = repository_service(
                        request, session, run.project_id, run.requested_by_user_id
                    ).pin_run(run.id, run.session_id)
                envelope["tools"] = definitions(session, run)
                envelope["server_time"] = utc_now().isoformat()
                from polycolab.agents.context import manifest_artifacts

                envelope["input_manifest"] = [
                    {"id": str(item.id), "sha256": item.sha256, "byte_length": item.byte_length}
                    for item in manifest_artifacts(session, manifest=manifest)
                ]
            response = JSONResponse(envelope)
            if len(response.body) > settings.runtime_api_max_response_bytes:
                _finish_claim_failure(
                    session, run, payload.worker_id, "execution_envelope_too_large"
                )
                metrics.increment("polycolab_runtime_claims_total", outcome="envelope_too_large")
                return Response(status_code=status.HTTP_204_NO_CONTENT)
            metrics.increment("polycolab_runtime_claims_total", outcome="claimed")
            return response
        except ContextInvalid, ToolCapabilityInvalid, SessionNotFound, RepositoryError:
            session.rollback()
            _finish_claim_failure(session, run, payload.worker_id, "context_unavailable")
            metrics.increment("polycolab_runtime_claims_total", outcome="context_unavailable")
            return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        session.close()


class CodexModelRequest(LeaseRequest):
    body: dict[str, object]
    request_id: str = Field(min_length=1, max_length=200)


@router.post("/runs/{run_id}/responses")
async def codex_response(
    run_id: UUID, payload: CodexModelRequest, request: Request
) -> dict[str, str]:
    from polycolab.model_gateway.hosted import respond

    _authorize_worker(request)
    from polycolab.model_gateway.service import ProviderFailure

    try:
        return await respond(
            request,
            run_id=run_id,
            worker_id=payload.worker_id,
            generation=payload.lease_generation,
            request_key=payload.request_id,
            body=payload.body,
        )
    except LeaseLost:
        raise RuntimeApiConflict("lease_lost") from None
    except ProviderFailure as exc:
        raise RuntimeApiConflict(exc.code) from None


def _lease_or_conflict(
    session: Session, run_id: UUID, payload: LeaseRequest, lease_seconds: int
) -> SqlAgentRun:
    if not renew_lease(
        session,
        run_id=run_id,
        worker_id=payload.worker_id,
        lease_generation=payload.lease_generation,
        lease_for=timedelta(seconds=lease_seconds),
    ):
        raise RuntimeApiConflict("lease_lost")
    run = session.get(SqlAgentRun, run_id)
    if run is None:
        raise RuntimeApiConflict("lease_lost")
    return run


@router.post("/runs/{run_id}/lease")
def heartbeat(run_id: UUID, payload: LeaseRequest, request: Request) -> dict[str, object]:
    _authorize_worker(request)
    session = request.app.state.session_factory()
    try:
        run = _lease_or_conflict(
            session, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        if run.runtime_spec and not workspace_policy.can(
            SqlAlchemyTransaction(session),
            run.project_id,
            run.requested_by_user_id,
            WorkspaceAction.RUN_AGENTS,
        ):
            raise RuntimeApiConflict("authorization_revoked")
        deadline = run.deadline_at
        timed_out = (
            deadline is not None
            and (
                deadline.replace(tzinfo=UTC)
                if deadline.tzinfo is None
                else deadline.astimezone(UTC)
            )
            <= utc_now()
        )
        return {
            "active": True,
            "cancel_requested": run.status is AgentRunStatus.CANCELLING,
            "timed_out": timed_out,
        }
    finally:
        session.close()


@router.post("/runs/{run_id}/model-grants")
def issue_model_grant(run_id: UUID, payload: LeaseRequest, request: Request) -> dict[str, str]:
    _authorize_worker(request)
    settings = request.app.state.settings
    session = request.app.state.session_factory()
    try:
        run = _lease_or_conflict(session, run_id, payload, settings.runtime_lease_seconds)
        if run.status is not AgentRunStatus.RUNNING or not workspace_policy.can(
            SqlAlchemyTransaction(session),
            run.project_id,
            run.requested_by_user_id,
            WorkspaceAction.RUN_AGENTS,
        ):
            raise RuntimeApiConflict("authorization_revoked")
        try:
            enforce_next_round_budget(
                session, run=run, limits=_execution_limits(request), now=utc_now()
            )
            session.commit()
            grant = issue_run_grant(
                session,
                user_id=run.requested_by_user_id,
                profile_id=run.gateway_profile_id,
                run_id=run.id,
                model_id=run.gateway_model_id,
                ttl_seconds=settings.gateway_run_token_ttl_seconds,
                max_ttl_seconds=settings.gateway_run_token_ttl_seconds,
                expected_credential_version=run.gateway_credential_version,
            )
        except ExecutionLimitExceeded as exc:
            session.rollback()
            raise RuntimeApiConflict(exc.code) from exc
        except GrantInvalid as exc:
            session.rollback()
            raise RuntimeApiConflict("gateway_profile_changed") from exc
        return {"grant": grant}
    finally:
        session.close()


@router.post("/runs/{run_id}/events")
def append_event(run_id: UUID, payload: EventRequest, request: Request) -> dict[str, int]:
    _authorize_worker(request)
    session = request.app.state.session_factory()
    try:
        try:
            event = append_worker_event(
                session,
                run_id=run_id,
                worker_id=payload.worker_id,
                lease_generation=payload.lease_generation,
                idempotency_key=payload.idempotency_key,
                kind=AgentRunEventKind(payload.kind),
                payload=payload.payload,
            )
        except LeaseLost as exc:
            raise RuntimeApiConflict("lease_lost") from exc
        except IdempotencyConflict as exc:
            raise RuntimeApiConflict("idempotency_conflict") from exc
        return {"cursor": event.cursor}
    finally:
        session.close()


@router.post("/runs/{run_id}/usage")
def append_usage(run_id: UUID, payload: UsageRequest, request: Request) -> dict[str, object]:
    _authorize_worker(request)
    settings = request.app.state.settings
    session = request.app.state.session_factory()
    try:
        try:
            usage = record_usage(
                session,
                run_id=run_id,
                worker_id=payload.worker_id,
                lease_generation=payload.lease_generation,
                idempotency_key=payload.idempotency_key,
                source=UsageSource.PROVIDER_REPORTED,
                input_tokens=payload.input_tokens,
                output_tokens=payload.output_tokens,
                total_tokens=payload.total_tokens,
                input_microusd_per_million_tokens=settings.gateway_input_microusd_per_million_tokens,
                output_microusd_per_million_tokens=settings.gateway_output_microusd_per_million_tokens,
            )
        except LeaseLost as exc:
            raise RuntimeApiConflict("lease_lost") from exc
        except IdempotencyConflict as exc:
            raise RuntimeApiConflict("idempotency_conflict") from exc
        return {"event_cursor": usage.event_cursor}
    finally:
        session.close()


@router.post("/runs/{run_id}/finish", status_code=status.HTTP_204_NO_CONTENT)
def finish(run_id: UUID, payload: FinishRequest, request: Request) -> Response:
    _authorize_worker(request)
    session = request.app.state.session_factory()
    try:
        try:
            existing = session.get(SqlAgentRun, run_id)
            if existing is not None and existing.runtime_spec:
                from polycolab.db.stores.repositories import SqlRepositoryStore

                binding = SqlRepositoryStore(session).run(run_id)
                if (
                    payload.status == "COMPLETED"
                    and binding is not None
                    and binding.output_commit is None
                ):
                    raise RuntimeApiConflict("repository_save_required")
                from polycolab.agents.recovery import complete

                complete(
                    session,
                    run_id=run_id,
                    worker_id=payload.worker_id,
                    generation=payload.lease_generation,
                    status=AgentRunStatus(payload.status),
                    failure_code=payload.failure_code,
                    final_message_md=payload.final_message_md,
                )
                return Response(status_code=204)
            finish_run(
                session,
                run_id=run_id,
                worker_id=payload.worker_id,
                lease_generation=payload.lease_generation,
                status=AgentRunStatus(payload.status),
                failure_code=payload.failure_code,
                final_message_md=payload.final_message_md,
            )
        except IdempotencyConflict:
            raise RuntimeApiConflict("completion_conflict") from None
        except LeaseLost as exc:
            session.rollback()
            existing = session.get(SqlAgentRun, run_id)
            if existing is not None and existing.runtime_spec:
                raise RuntimeApiConflict("lease_lost") from exc
            if (
                existing is None
                or existing.lease_generation != payload.lease_generation
                or existing.status.value != payload.status
                or existing.failure_code != payload.failure_code
            ):
                raise RuntimeApiConflict("lease_lost") from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        session.close()


@router.post("/runs/{run_id}/terminated", status_code=204)
def confirm_runtime_termination(run_id: UUID, payload: LeaseRequest, request: Request) -> Response:
    from polycolab.execution.allocator import confirm_termination

    _authorize_worker(request)
    with request.app.state.session_factory() as session:
        try:
            confirm_termination(
                session, run_id=run_id, generation=payload.lease_generation, owner=payload.worker_id
            )
        except ValueError:
            raise RuntimeApiConflict("slot_not_found") from None
    return Response(status_code=204)


class ExecutorReadiness(RuntimeRequest):
    image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capacity: int = Field(ge=0, le=64)
    slot_states: dict[int, Literal["AVAILABLE", "BUSY", "QUARANTINED"]] = Field(
        default_factory=dict, max_length=64
    )


@router.post("/executors/readiness", status_code=204)
def executor_readiness(payload: ExecutorReadiness, request: Request) -> Response:
    from polycolab.execution.hosts import HostConflict, advertise

    _authorize_worker(request)
    configured = request.app.state.settings.runtime_codex_image
    if configured is None or configured.rsplit("@sha256:", 1)[-1] != payload.image_digest:
        raise RuntimeApiConflict("runtime_image_mismatch")
    if payload.incarnation is None:
        raise RuntimeApiConflict("executor_protocol_mismatch")
    with request.app.state.session_factory() as session:
        try:
            advertise(
                session,
                worker_id=payload.worker_id,
                incarnation=payload.incarnation,
                image=payload.image_digest,
                states=dict(payload.slot_states),
                protocol=payload.protocol_version,
            )
        except HostConflict as exc:
            raise RuntimeApiConflict(str(exc)) from None
    return Response(status_code=204)

"""Redacted, authenticated operator diagnostics for a canonical run."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.access.authorization import AuthorizationDenied, WorkspaceNotFound
from polycolab.accounts.authentication import current_principal
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentRunUsage,
    SqlAgentSession,
    SqlOperatorDiagnosticAccess,
    SqlPlatformAgentVersion,
    SqlRuntimeRunBinding,
    SqlRunToolCapability,
)
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus
from polycolab.entities.time import utc_now
from polycolab.operations.schemas import OperatorRunDiagnostics

router = APIRouter(prefix="/internal/v1/ops", include_in_schema=False)


def _failure_class(run: SqlAgentRun) -> str | None:
    if run.status is AgentRunStatus.COMPLETED:
        return None
    if run.status is AgentRunStatus.CANCELLED:
        return "cancelled"
    if run.status is AgentRunStatus.TIMED_OUT:
        return "timeout"
    code = run.failure_code or ""
    if code.startswith(("model_", "provider_", "gateway_")):
        return "provider"
    if code.startswith(("execution_", "output_limit", "deadline_")):
        return "limit"
    if code.startswith(("authorization_", "context_", "tool_")):
        return "policy"
    return "runtime" if run.status is AgentRunStatus.FAILED else None


def _seconds(later: datetime | None, earlier: datetime | None) -> float | None:
    if later is None or earlier is None:
        return None
    return max(
        0.0,
        (later.astimezone(UTC) - earlier.astimezone(UTC)).total_seconds(),
    )


def _operator_allowed(request: Request) -> str:
    settings = request.app.state.settings
    if not settings.operator_diagnostics_enabled:
        raise WorkspaceNotFound
    principal = current_principal(request)
    if principal.subject not in settings.operator_diagnostics_subjects:
        raise AuthorizationDenied
    # Persist only a stable one-way identifier, never the OIDC identity claim.
    return sha256(f"{principal.issuer}\x00{principal.subject}".encode()).hexdigest()


def _int(value: object) -> int:
    return int(value) if isinstance(value, int | float) else 0


@router.get("/runs/{run_id}", response_model=OperatorRunDiagnostics)
def get_operator_run_diagnostics(run_id: UUID, request: Request) -> OperatorRunDiagnostics:
    operator_digest = _operator_allowed(request)
    session: Session = request.app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        if run is None:
            raise WorkspaceNotFound
        run_session = session.get(SqlAgentSession, run.session_id)
        if run_session is None:
            raise WorkspaceNotFound
        agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
        if agent is None:
            raise WorkspaceNotFound
        runtime_binding = session.scalar(
            select(SqlRuntimeRunBinding).where(SqlRuntimeRunBinding.run_id == run.id)
        )
        event_count, first_cursor, last_cursor = session.execute(
            select(
                func.count(SqlAgentRunEvent.id),
                func.min(SqlAgentRunEvent.cursor),
                func.max(SqlAgentRunEvent.cursor),
            ).where(SqlAgentRunEvent.run_id == run.id)
        ).one()
        first_delta_at = session.scalar(
            select(func.min(SqlAgentRunEvent.occurred_at)).where(
                SqlAgentRunEvent.run_id == run.id,
                SqlAgentRunEvent.kind == AgentRunEventKind.ASSISTANT_DELTA,
            )
        )
        usage_input, usage_output, usage_total = session.execute(
            select(
                func.coalesce(func.sum(SqlAgentRunUsage.input_tokens), 0),
                func.coalesce(func.sum(SqlAgentRunUsage.output_tokens), 0),
                func.coalesce(func.sum(SqlAgentRunUsage.total_tokens), 0),
            ).where(SqlAgentRunUsage.run_id == run.id)
        ).one()
        capabilities = list(
            session.scalars(
                select(SqlRunToolCapability).where(SqlRunToolCapability.run_id == run.id)
            )
        )
        now = utc_now()
        capability_expired = sum(
            capability.expires_at.astimezone(UTC) <= now for capability in capabilities
        )
        capability_revoked = sum(capability.revoked for capability in capabilities)
        capability_active = sum(
            not capability.revoked and capability.expires_at.astimezone(UTC) > now
            for capability in capabilities
        )
        session.add(
            SqlOperatorDiagnosticAccess(
                run_id=run.id,
                operator_subject_digest=operator_digest,
                request_id=UUID(request.state.request_id),
            )
        )
        session.commit()
        settings = request.app.state.settings
        return OperatorRunDiagnostics(
            run_id=run.id,
            session_status=run_session.status,
            status=run.status,
            created_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            attempt=run.attempt,
            retry_count=max(0, run.attempt - 1),
            lease_generation=run.lease_generation,
            lease_active=(
                run.lease_owner is not None
                and run.lease_expires_at is not None
                and run.lease_expires_at.astimezone(UTC) > now
            ),
            lease_expires_at=run.lease_expires_at,
            agent_kind=agent.agent_kind,
            agent_version=agent.version,
            release_sha=settings.release_sha,
            runtime_binding_status=(runtime_binding.status.value if runtime_binding else None),
            event_count=_int(event_count),
            first_event_cursor=_int(first_cursor) if first_cursor is not None else None,
            last_event_cursor=_int(last_cursor) if last_cursor is not None else None,
            terminal_outcome=(
                run.status.value
                if run.status
                in {
                    AgentRunStatus.COMPLETED,
                    AgentRunStatus.CANCELLED,
                    AgentRunStatus.FAILED,
                    AgentRunStatus.TIMED_OUT,
                }
                else None
            ),
            failure_class=_failure_class(run),
            queue_wait_seconds=_seconds(run.started_at, run.created_at),
            time_to_first_token_seconds=_seconds(first_delta_at, run.started_at),
            duration_seconds=_seconds(run.finished_at, run.started_at),
            usage_input_tokens=_int(usage_input),
            usage_output_tokens=_int(usage_output),
            usage_total_tokens=_int(usage_total),
            capability_total=len(capabilities),
            capability_active=capability_active,
            capability_expired=capability_expired,
            capability_revoked=capability_revoked,
            feature_agent_execution_enabled=settings.feature_agent_execution_enabled,
            authorization_decision_reason_class="operator_allowlisted",
            links={
                "metrics": "/internal/v1/metrics",
                "incident_runbook": "docs/operations/incident-runbooks.md",
                "deployment_evidence": "docs/staging/evidence-template.md",
            },
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

"""Fenced hosted export reservations and storage acknowledgements."""

from dataclasses import replace
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import ActorOperation
from polycolab.access.authorization import ProjectAction
from polycolab.agents.access import _run_scope
from polycolab.agents.recovery import lock_run
from polycolab.agents.runtime.artifacts import UploadRequest
from polycolab.agents.runtime.errors import RuntimeApiConflict
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.agents.sessions import _require_live_lease
from polycolab.agents.tools import _actor_for_validated_tool
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import ArtifactUploadDeclaration
from polycolab.db.converters.artifacts import artifact as artifact_snapshot
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlHostedRunArtifact,
    SqlResearchScope,
    SqlRunToolCapability,
)
from polycolab.entities.enums import AgentRunStatus, ArtifactState
from polycolab.entities.time import utc_now
from polycolab.execution.allocator import utc
from polycolab.platform.config import Settings


def reserve_export(
    session: Session, run_id: UUID, payload: UploadRequest, settings: Settings
) -> artifacts.StoredArtifact:
    run = lock_run(session, run_id)
    _require_live_lease(
        run, worker_id=payload.worker_id, lease_generation=payload.lease_generation, now=utc_now()
    )
    if run.status != AgentRunStatus.RUNNING:
        raise RuntimeApiConflict("cancel_requested")
    spec = RuntimeSpec.model_validate(run.runtime_spec)
    scope = session.scalar(
        select(SqlResearchScope).where(SqlResearchScope.project_id == run.project_id)
    )
    capability = session.scalar(
        select(SqlRunToolCapability).where(
            SqlRunToolCapability.run_id == run_id,
            SqlRunToolCapability.lease_generation == payload.lease_generation,
            SqlRunToolCapability.revoked.is_(False),
            SqlRunToolCapability.expires_at > utc_now(),
        )
    )
    if scope is None or capability is None:
        raise RuntimeApiConflict("authorization_revoked")
    # Project authorization and the run row serialize count/byte reservations.
    _run_scope(
        session,
        run_id=run_id,
        user_id=run.requested_by_user_id,
        action=ProjectAction.RUN_AGENTS,
    )
    session.execute(select(SqlAgentRun).where(SqlAgentRun.id == run_id).with_for_update())
    rows = list(
        session.execute(
            select(SqlHostedRunArtifact, SqlArtifact)
            .join(SqlArtifact)
            .where(
                SqlHostedRunArtifact.run_id == run_id,
                SqlHostedRunArtifact.generation == payload.lease_generation,
            )
        )
    )
    for binding, artifact in rows:
        if binding.path == payload.path:
            if (
                binding.generation != payload.lease_generation
                or binding.display_name != payload.display_name
                or artifact.sha256 != payload.sha256
                or artifact.byte_length != payload.byte_length
                or artifact.media_type != payload.media_type
            ):
                raise RuntimeApiConflict("artifact_export_conflict")
            return artifact_snapshot(artifact)
    if (
        len(rows) >= spec.limits.output_files
        or sum(row.byte_length for _, row in rows) + payload.byte_length > spec.limits.output_bytes
    ):
        raise RuntimeApiConflict("artifact_output_limit")
    actor = replace(
        _actor_for_validated_tool(capability, run=run, tool_name="export_artifact"),
        ownership_scope_id=scope.id,
        operation_scope=frozenset({ActorOperation.PROJECT_WRITE}),
    )
    row = artifacts.reserve(
        session,
        project_id=run.project_id,
        user_id=run.requested_by_user_id,
        declaration=ArtifactUploadDeclaration(
            sha256=payload.sha256,
            byte_length=payload.byte_length,
            media_type=payload.media_type,
        ),
        settings=settings,
        actor=actor,
        commit=False,
    )
    session.add(
        SqlHostedRunArtifact(
            artifact_id=row.id,
            run_id=run_id,
            generation=payload.lease_generation,
            path=payload.path,
            display_name=payload.display_name,
        )
    )
    session.commit()
    return row


def verify_export(
    session: Session, run_id: UUID, payload: UploadRequest, artifact_id: UUID
) -> None:
    run = lock_run(session, run_id)
    _require_live_lease(
        run, worker_id=payload.worker_id, lease_generation=payload.lease_generation, now=utc_now()
    )
    _run_scope(
        session, run_id=run_id, user_id=run.requested_by_user_id, action=ProjectAction.RUN_AGENTS
    )
    artifact = session.scalar(
        select(SqlArtifact).where(SqlArtifact.id == artifact_id).with_for_update()
    )
    if (
        run.status != AgentRunStatus.RUNNING
        or artifact is None
        or artifact.state != ArtifactState.STAGING
        or utc(artifact.expires_at) <= utc_now()
    ):
        raise RuntimeApiConflict("artifact_export_expired")
    artifact.verified_at = utc_now()
    session.commit()

"""Requested run rights are immutable; effective authority always uses current policy."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import AuthorizationDenied, WorkspaceAction, workspace_policy
from polycolab.agents.schemas import RunAuthorityRequest
from polycolab.db.models import (
    SqlAgentRun,
    SqlCatalogueEntry,
    SqlPlatformAgentVersion,
    SqlResearchObject,
    SqlRunWriteGrant,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.platform.outbox import canonical_digest
from polycolab.research.records import accessible_revision, public_revision


def requested(session: Session, run_id: UUID) -> RunAuthorityRequest | None:
    grant = session.get(SqlRunWriteGrant, run_id)
    if grant is None:
        return None
    if grant.request_digest != canonical_digest(grant.request):
        raise AuthorizationDenied("invalid run authority")
    try:
        return RunAuthorityRequest.model_validate(grant.request)
    except ValidationError as exc:
        raise AuthorizationDenied("invalid run authority") from exc


def validate(
    session: Session,
    *,
    project_id: UUID,
    user_id: UUID,
    agent_version_id: UUID,
    context_ids: list[UUID],
    authority: RunAuthorityRequest,
) -> None:
    version = session.get(SqlPlatformAgentVersion, agent_version_id)
    if version is None or version.version != 2:
        raise AuthorizationDenied("this agent version has no direct contribution tools")
    workspace_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user_id, WorkspaceAction.RUN_AGENTS
    )
    if authority.destination == "WORKSPACE":
        workspace_policy.require_scope(
            SqlAlchemyTransaction(session), project_id, user_id, WorkspaceAction.CREATE_RESEARCH
        )
    inputs = {
        revision_id: accessible_revision(
            session,
            revision_id,
            project_id if authority.destination == "WORKSPACE" else None,
        )
        for revision_id in context_ids
    }
    for target_id in authority.public_target_revision_ids:
        if target_id not in inputs:
            raise AuthorizationDenied("public targets must be explicitly pinned inputs")
        public_revision(session, target_id)
    for object_id in authority.editable_object_ids:
        obj = session.scalar(select(SqlResearchObject).where(SqlResearchObject.id == object_id))
        if (
            obj is None
            or obj.created_by_user_id != user_id
            or session.get(SqlCatalogueEntry, object_id) is not None
            or not any(row.object_id == object_id for row in inputs.values())
            or (authority.destination == "WORKSPACE" and obj.project_id != project_id)
            or (authority.destination == "PUBLIC" and obj.project_id is not None)
        ):
            raise AuthorizationDenied("record is outside editing authority; use a suggestion")


def attach(session: Session, run: SqlAgentRun, authority: RunAuthorityRequest) -> None:
    validate(
        session,
        project_id=run.project_id,
        user_id=run.requested_by_user_id,
        agent_version_id=run.agent_version_id,
        context_ids=[UUID(value) for value in run.requested_context_revision_ids],
        authority=authority,
    )
    session.flush()
    body = authority.model_dump(mode="json")
    session.add(
        SqlRunWriteGrant(run_id=run.id, request=body, request_digest=canonical_digest(body))
    )

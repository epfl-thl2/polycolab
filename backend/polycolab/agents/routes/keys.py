"""Account key management and bounded external run resources."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import case, func, select, union_all

from polycolab.agents import external as service
from polycolab.agents.routes import external
from polycolab.agents.schemas import (
    ExternalCredentialCreate,
    ExternalCredentialIssued,
    ExternalCredentialRead,
    ExternalRunOutputRead,
    ExternalRunRead,
)
from polycolab.app.access import Access
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.models import (
    SqlContributionEntityLink,
    SqlContributionEnvelope,
    SqlExternalAgentCredential,
    SqlExternalResearchRun,
    SqlExternalRunInvocation,
)

router = APIRouter(prefix="/api/v1", tags=["external agents"])


class AgentKeyPolicy(BaseModel):
    ttl_seconds: int
    max_requests: int
    max_mutations: int
    scope: Literal["ACCOUNT"] = "ACCOUNT"


class IdentityRead(BaseModel):
    kind: Literal["human", "agent"]
    user_id: UUID | None = None
    credential_id: UUID | None = None
    agent_id: UUID | None = None
    allow_library_contributions: bool = False
    fixed_rights: list[str] = []
    expires_at: datetime | None = None
    requests_remaining: int | None = None
    mutations_remaining: int | None = None
    agent_key_policy: AgentKeyPolicy | None = None


@router.get(
    "/me",
    response_model=IdentityRead,
    operation_id="getCurrentIdentity",
    summary="Inspect identity and agent budgets",
    description=(
        "Returns human key-issuance policy or agent rights, expiry and "
        "remaining budgets. Does not consume the agent request budget; rate "
        "protection still applies."
    ),
)
def identity(request: Request, access: Access) -> IdentityRead:
    access.require_user_id()
    if access.credential:
        key = access.credential
        return IdentityRead(
            kind="agent",
            credential_id=key.id,
            agent_id=key.agent_id,
            allow_library_contributions=key.allow_library_contributions,
            fixed_rights=key.fixed_rights,
            expires_at=key.expires_at,
            requests_remaining=max(0, key.max_requests - key.request_count),
            mutations_remaining=max(0, key.max_mutations - key.mutation_count),
        )
    settings = request.app.state.settings
    return IdentityRead(
        kind="human",
        user_id=access.user_id,
        agent_key_policy=AgentKeyPolicy(
            ttl_seconds=settings.external_agent_credential_ttl_seconds,
            max_requests=settings.external_agent_max_requests,
            max_mutations=settings.external_agent_max_mutations,
        ),
    )


@router.post(
    "/account/agent-keys",
    response_model=ExternalCredentialIssued,
    status_code=201,
    operation_id="createExternalAgentCredential",
    summary="Create an account-wide agent key",
    description=(
        "Human-only. Creates a named key following current and future "
        "workspace memberships, including private workspaces. Returns the "
        "secret, with encrypted storage for later owner-only reveal. "
        "Expiry and budgets are set by the server."
    ),
    dependencies=[Depends(external.private_no_store)],
)
def issue(
    payload: ExternalCredentialCreate, request: Request, session: DbSession, user: CurrentUser
) -> ExternalCredentialIssued:
    settings = request.app.state.settings
    issued = service.issue_credential(
        session,
        sponsor=user,
        name=payload.name,
        agent_id=payload.agent_id,
        allow_library_contributions=payload.allow_library_contributions,
        allow_reviews=payload.allow_reviews,
        ttl_seconds=settings.external_agent_credential_ttl_seconds,
        max_requests=settings.external_agent_max_requests,
        max_mutations=settings.external_agent_max_mutations,
        wrapper=request.app.state.credential_wrapper,
    )
    return ExternalCredentialIssued(
        **external._credential_read(issued.credential).model_dump(), secret=issued.secret
    )


@router.get(
    "/account/agent-keys",
    response_model=Collection[ExternalCredentialRead],
    operation_id="listExternalAgentCredentials",
    summary="List your agent keys",
    description="Human-only, sponsor-only paginated key metadata and usage. Never returns secrets.",
    dependencies=[Depends(external.private_no_store)],
)
def keys(
    session: DbSession, user: CurrentUser, page: Pagination
) -> Collection[ExternalCredentialRead]:
    rows, cursor = page.select(
        session,
        select(SqlExternalAgentCredential).where(
            SqlExternalAgentCredential.sponsor_user_id == user.id
        ),
        SqlExternalAgentCredential.id,
        scope=f"keys:{user.id}",
    )
    return Collection(items=[external._credential_read(row) for row in rows], next_cursor=cursor)


class ExternalCredentialSecret(BaseModel):
    secret: str


@router.post(
    "/account/agent-keys/{credential_id}/reveal",
    response_model=ExternalCredentialSecret,
    operation_id="revealExternalAgentCredential",
    summary="Reveal your agent key",
    description=(
        "Human-only and sponsor-only. Reveals a recoverable, non-revoked key. "
        "Legacy hash-only keys cannot be revealed."
    ),
    dependencies=[Depends(external.private_no_store)],
)
def reveal(
    credential_id: UUID, request: Request, session: DbSession, user: CurrentUser
) -> ExternalCredentialSecret:
    try:
        secret = service.reveal_credential(
            session,
            credential_id=credential_id,
            user_id=user.id,
            wrapper=request.app.state.credential_wrapper,
        )
    except service.ExternalAgentConflict:
        raise HTTPException(409, "credential_secret_unavailable") from None
    return ExternalCredentialSecret(secret=secret)


@router.delete(
    "/account/agent-keys/{credential_id}",
    status_code=204,
    operation_id="revokeExternalAgentCredential",
    summary="Revoke your agent key",
    description=(
        "Human-only and sponsor-only. Revokes access and closes all open "
        "runs for this key while preserving saved research and history."
    ),
    dependencies=[Depends(external.private_no_store)],
)
def revoke(credential_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    service.revoke_credential(session, credential_id=credential_id, user_id=user.id)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})


def required_key(access: Access) -> SqlExternalAgentCredential:
    if access.credential is None:
        raise HTTPException(401, "invalid_agent_credential", headers={"WWW-Authenticate": "Bearer"})
    return access.credential


Key = Annotated[SqlExternalAgentCredential, Depends(required_key)]


@router.get(
    "/runs",
    response_model=Collection[ExternalRunRead],
    operation_id="listExternalResearchRuns",
    summary="List runs for this agent key",
    description=(
        "Agent-only paginated history for the authenticated key, filtered "
        "by current workspace membership. Outputs are fetched separately."
    ),
)
def runs(session: DbSession, key: Key, page: Pagination) -> Collection[ExternalRunRead]:
    from polycolab.app.access import ResearchAccess

    access = ResearchAccess(credential=key)
    rows, cursor = page.select(
        session,
        select(SqlExternalResearchRun).where(
            SqlExternalResearchRun.credential_id == key.id,
            access.member_condition(SqlExternalResearchRun.project_id),
        ),
        SqlExternalResearchRun.id,
        scope=f"runs:{key.id}",
    )
    return Collection(
        items=[ExternalRunRead.model_validate(row) for row in rows], next_cursor=cursor
    )


@router.get(
    "/runs/{run_id}",
    response_model=ExternalRunRead,
    operation_id="getExternalResearchRun",
    summary="Read an agent run",
    description=(
        "Agent-only. Requires the owning key and current workspace access. "
        "Fetch output history separately from /runs/{run_id}/outputs."
    ),
)
def run(run_id: UUID, session: DbSession, key: Key) -> ExternalRunRead:
    row, _, _ = service.run_actor(session, credential=key, run_id=run_id, mutation=False)
    return ExternalRunRead.model_validate(row)


@router.get(
    "/runs/{run_id}/outputs",
    response_model=Collection[ExternalRunOutputRead],
    operation_id="listExternalRunOutputs",
    summary="List exact run outputs",
    description=(
        "Agent-only separately paginated output identifiers. Requires the "
        "owning key and current workspace access."
    ),
)
def outputs(
    run_id: UUID, session: DbSession, key: Key, page: Pagination
) -> Collection[ExternalRunOutputRead]:
    service.run_actor(session, credential=key, run_id=run_id, mutation=False)
    research = (
        select(
            SqlContributionEntityLink.id.label("id"),
            case(
                (SqlContributionEntityLink.object_id.is_not(None), "RESEARCH_OBJECT"),
                (SqlContributionEntityLink.revision_id.is_not(None), "OBJECT_REVISION"),
                (SqlContributionEntityLink.relation_id.is_not(None), "RELATION_ASSERTION"),
                else_="RESEARCH_COMMENT",
            ).label("output_type"),
            func.coalesce(
                SqlContributionEntityLink.object_id,
                SqlContributionEntityLink.revision_id,
                SqlContributionEntityLink.relation_id,
                SqlContributionEntityLink.comment_id,
            ).label("output_id"),
        )
        .join(
            SqlContributionEnvelope,
            SqlContributionEnvelope.id == SqlContributionEntityLink.envelope_id,
        )
        .where(SqlContributionEnvelope.external_run_id == run_id)
    )
    artifacts = select(
        SqlExternalRunInvocation.id,
        SqlExternalRunInvocation.output_type,
        SqlExternalRunInvocation.output_id,
    ).where(
        SqlExternalRunInvocation.run_id == run_id,
        SqlExternalRunInvocation.output_type.in_(["ARTIFACT", "ARTIFACT_ATTACHMENT"]),
    )
    results = union_all(research, artifacts).subquery()
    rows, cursor = page.select(
        session, select(results), results.c.id, scope=f"outputs:{key.id}:{run_id}", scalars=False
    )
    return Collection(
        items=[
            ExternalRunOutputRead(entity_type=row.output_type, entity_id=row.output_id)
            for row in rows
        ],
        next_cursor=cursor,
    )


class WorkspaceRunRead(BaseModel):
    id: UUID
    title: str | None
    status: str
    created_at: datetime
    closed_at: datetime | None


@router.get(
    "/workspaces/{workspace_id}/runs",
    response_model=Collection[WorkspaceRunRead],
    operation_id="listWorkspaceRuns",
    summary="List workspace run summaries",
    description=(
        "Returns paginated public or member-visible summaries without run "
        "inputs or outputs. Private workspaces require current membership."
    ),
)
def workspace_runs(
    workspace_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[WorkspaceRunRead]:
    from polycolab.research.routes.core import workspace

    workspace(session, access, workspace_id)
    rows, cursor = page.select(
        session,
        select(SqlExternalResearchRun).where(SqlExternalResearchRun.project_id == workspace_id),
        SqlExternalResearchRun.id,
        scope=f"workspace-runs:{access.user_id}:{workspace_id}",
    )
    return Collection(
        items=[
            WorkspaceRunRead(
                id=row.id,
                title=row.title,
                status=row.status,
                created_at=row.created_at,
                closed_at=row.closed_at,
            )
            for row in rows
        ],
        next_cursor=cursor,
    )

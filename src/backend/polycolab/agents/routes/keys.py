"""Account key management and bounded external run resources."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from polycolab.agents import external as service
from polycolab.agents.schemas import (
    ExternalCredentialCreate,
    ExternalCredentialIssued,
    ExternalCredentialRead,
)
from polycolab.app.access import Access
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.models import (
    SqlExternalAgentCredential,
)
from polycolab.platform.project_history import credential_right


def private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _credential_read(row: SqlExternalAgentCredential) -> ExternalCredentialRead:
    return ExternalCredentialRead.model_validate(row)


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
            fixed_rights=[credential_right(value) for value in key.fixed_rights],
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
        "project memberships, including private projects. Returns the "
        "secret, with encrypted storage for later owner-only reveal. "
        "Expiry and budgets are set by the server."
    ),
    dependencies=[Depends(private_no_store)],
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
        ttl_seconds=settings.external_agent_credential_ttl_seconds,
        max_requests=settings.external_agent_max_requests,
        max_mutations=settings.external_agent_max_mutations,
        wrapper=request.app.state.credential_wrapper,
    )
    return ExternalCredentialIssued(
        **_credential_read(issued.credential).model_dump(), secret=issued.secret
    )


@router.get(
    "/account/agent-keys",
    response_model=Collection[ExternalCredentialRead],
    operation_id="listExternalAgentCredentials",
    summary="List your agent keys",
    description="Human-only, sponsor-only paginated key metadata and usage. Never returns secrets.",
    dependencies=[Depends(private_no_store)],
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
    return Collection(items=[_credential_read(row) for row in rows], next_cursor=cursor)


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
    dependencies=[Depends(private_no_store)],
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
    description=("Human-only and sponsor-only. Revokes file access for this key."),
    dependencies=[Depends(private_no_store)],
)
def revoke(credential_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    service.revoke_credential(session, credential_id=credential_id, user_id=user.id)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})

"""Account key management and bounded external run resources."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from polycolab.agents import external as service
from polycolab.agents.schemas import (
    AgentApiKeyCreate,
    AgentApiKeyIssued,
    AgentApiKeyRead,
)
from polycolab.app.access import Access
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.models import (
    SqlAgentApiKey,
)
from polycolab.platform.project_history import credential_right


def private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _credential_read(row: SqlAgentApiKey) -> AgentApiKeyRead:
    return AgentApiKeyRead.model_validate(row)


router = APIRouter(prefix="/api/v1", tags=["external agents"])


class AgentKeyPolicy(BaseModel):
    ttl_seconds: int
    max_requests: int
    max_writes: int
    scope: Literal["ACCOUNT"] = "ACCOUNT"


class IdentityRead(BaseModel):
    kind: Literal["human", "agent"]
    user_id: UUID | None = None
    credential_id: UUID | None = None
    fixed_rights: list[str] = []
    expires_at: datetime | None = None
    requests_remaining: int | None = None
    writes_remaining: int | None = None
    agent_key_policy: AgentKeyPolicy | None = None


@router.get(
    "/me",
    response_model=IdentityRead,
    operation_id="getCurrentIdentity",
    summary="Inspect identity and agent limits",
    description=(
        "Returns human key-issuance policy or agent rights, expiry and "
        "remaining limits. Does not consume the agent request budget; rate "
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
            fixed_rights=[credential_right(value) for value in key.fixed_rights],
            expires_at=key.expires_at,
            requests_remaining=max(0, key.max_requests - key.request_count),
            writes_remaining=max(0, key.max_writes - key.write_count),
        )
    settings = request.app.state.settings
    return IdentityRead(
        kind="human",
        user_id=access.user_id,
        agent_key_policy=AgentKeyPolicy(
            ttl_seconds=settings.agent_api_key_ttl_seconds,
            max_requests=settings.agent_api_key_max_requests,
            max_writes=settings.agent_api_key_max_writes,
        ),
    )


@router.post(
    "/account/agent-keys",
    response_model=AgentApiKeyIssued,
    status_code=201,
    operation_id="createAgentApiKey",
    summary="Create an account-wide agent key",
    description=(
        "Human-only. Creates a named key following current and future "
        "project memberships, including private projects. Returns the "
        "secret, with encrypted storage for later owner-only reveal. "
        "Expiry and limits are set by the server."
    ),
    dependencies=[Depends(private_no_store)],
)
def issue(
    payload: AgentApiKeyCreate, request: Request, session: DbSession, user: CurrentUser
) -> AgentApiKeyIssued:
    settings = request.app.state.settings
    issued = service.issue_credential(
        session,
        owner=user,
        name=payload.name,
        ttl_seconds=settings.agent_api_key_ttl_seconds,
        max_requests=settings.agent_api_key_max_requests,
        max_writes=settings.agent_api_key_max_writes,
        wrapper=request.app.state.credential_wrapper,
    )
    return AgentApiKeyIssued(
        **_credential_read(issued.credential).model_dump(), secret=issued.secret
    )


@router.get(
    "/account/agent-keys",
    response_model=Collection[AgentApiKeyRead],
    operation_id="listAgentApiKeys",
    summary="List your agent keys",
    description="Human-only, owner-only paginated key metadata and usage. Never returns secrets.",
    dependencies=[Depends(private_no_store)],
)
def keys(session: DbSession, user: CurrentUser, page: Pagination) -> Collection[AgentApiKeyRead]:
    rows, cursor = page.select(
        session,
        select(SqlAgentApiKey).where(SqlAgentApiKey.owner_user_id == user.id),
        SqlAgentApiKey.id,
        scope=f"keys:{user.id}",
    )
    return Collection(items=[_credential_read(row) for row in rows], next_cursor=cursor)


class AgentApiKeySecret(BaseModel):
    secret: str


@router.post(
    "/account/agent-keys/{credential_id}/reveal",
    response_model=AgentApiKeySecret,
    operation_id="revealAgentApiKey",
    summary="Reveal your agent key",
    description=(
        "Human-only and owner-only. Reveals a recoverable, non-revoked key. "
        "Legacy hash-only keys cannot be revealed."
    ),
    dependencies=[Depends(private_no_store)],
)
def reveal(
    credential_id: UUID, request: Request, session: DbSession, user: CurrentUser
) -> AgentApiKeySecret:
    try:
        secret = service.reveal_credential(
            session,
            credential_id=credential_id,
            user_id=user.id,
            wrapper=request.app.state.credential_wrapper,
        )
    except service.ExternalAgentConflict:
        raise HTTPException(409, "credential_secret_unavailable") from None
    return AgentApiKeySecret(secret=secret)


@router.delete(
    "/account/agent-keys/{credential_id}",
    status_code=204,
    operation_id="revokeAgentApiKey",
    summary="Revoke your agent key",
    description=("Human-only and owner-only. Revokes file access for this key."),
    dependencies=[Depends(private_no_store)],
)
def revoke(credential_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    service.revoke_credential(session, credential_id=credential_id, user_id=user.id)
    return Response(status_code=204, headers={"Cache-Control": "private, no-store"})

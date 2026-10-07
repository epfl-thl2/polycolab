"""Human-owned external agent identities, independent of individual credentials."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from polycolab.agents.routes.external import private_no_store
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.db.models import SqlExternalAgentIdentity

router = APIRouter(
    prefix="/api/v1/account/agents", tags=["agent-keys"], dependencies=[Depends(private_no_store)]
)


class AgentIdentityWrite(RequestModel):
    name: str = Field(min_length=1, max_length=200)


class AgentIdentityRead(ApiModel):
    id: UUID
    name: str
    sponsor_user_id: UUID
    created_at: datetime


@router.post(
    "",
    response_model=AgentIdentityRead,
    status_code=201,
    operation_id="createExternalAgentIdentity",
)
def create(
    payload: AgentIdentityWrite, session: DbSession, user: CurrentUser
) -> SqlExternalAgentIdentity:
    identity = SqlExternalAgentIdentity(sponsor_user_id=user.id, name=payload.name)
    session.add(identity)
    session.commit()
    return identity


@router.get(
    "", response_model=Collection[AgentIdentityRead], operation_id="listExternalAgentIdentities"
)
def listing(
    session: DbSession, user: CurrentUser, page: Pagination
) -> Collection[AgentIdentityRead]:
    rows, cursor = page.select(
        session,
        select(SqlExternalAgentIdentity).where(SqlExternalAgentIdentity.sponsor_user_id == user.id),
        SqlExternalAgentIdentity.id,
        scope=f"agent-identities:{user.id}",
    )
    return Collection(
        items=[AgentIdentityRead.model_validate(row) for row in rows], next_cursor=cursor
    )


@router.patch(
    "/{agent_id}", response_model=AgentIdentityRead, operation_id="updateExternalAgentIdentity"
)
def update(
    agent_id: UUID, payload: AgentIdentityWrite, session: DbSession, user: CurrentUser
) -> SqlExternalAgentIdentity:
    identity = session.get(SqlExternalAgentIdentity, agent_id)
    if identity is None or identity.sponsor_user_id != user.id:
        raise HTTPException(404, "not_found")
    identity.name = payload.name
    session.commit()
    return identity

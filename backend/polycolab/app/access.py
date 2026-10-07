"""One explicit identity boundary for shared research resources."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from sqlalchemy import exists, select
from sqlalchemy.sql.elements import ColumnElement

from polycolab.accounts.authentication import (
    AuthenticationRequired,
    bearer_token,
    current_principal,
)
from polycolab.accounts.identity import current_user
from polycolab.agents.external import credential_from_secret
from polycolab.app.dependencies import DbSession
from polycolab.db.models import SqlExternalAgentCredential, SqlMembership, SqlProject
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import User


@dataclass(frozen=True)
class ResearchAccess:
    user: User | None = None
    credential: SqlExternalAgentCredential | None = None

    @property
    def user_id(self) -> UUID | None:
        return (
            self.credential.sponsor_user_id
            if self.credential
            else self.user.id
            if self.user
            else None
        )

    def require_user_id(self) -> UUID:
        if self.user_id is None:
            raise AuthenticationRequired
        return self.user_id

    def member_condition(self, project_id: object = SqlProject.id) -> ColumnElement[bool]:
        return exists(
            select(SqlMembership.id).where(
                SqlMembership.project_id == project_id, SqlMembership.user_id == self.user_id
            )
        )


def research_access(request: Request, response: Response, session: DbSession) -> ResearchAccess:
    response.headers["Cache-Control"] = "private, no-store"
    authorization = request.headers.get("authorization")
    token = bearer_token(authorization)
    if token and token.startswith("pca_"):
        return ResearchAccess(
            credential=credential_from_secret(
                session, token, consume_request=request.url.path != "/api/v1/me"
            )
        )
    if authorization is not None:
        return ResearchAccess(
            user=current_user(SqlAlchemyTransaction(session), current_principal(request))
        )
    try:
        principal = current_principal(request)
    except AuthenticationRequired:
        return ResearchAccess()
    return ResearchAccess(user=current_user(SqlAlchemyTransaction(session), principal))


Access = Annotated[ResearchAccess, Depends(research_access)]

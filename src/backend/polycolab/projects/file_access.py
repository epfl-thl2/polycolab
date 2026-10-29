"""Human and external-agent access to the same project filesystem."""

from dataclasses import dataclass, field
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, Response
from sqlalchemy import update
from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    ProjectNotFound,
)
from polycolab.accounts.authentication import bearer_token, current_principal
from polycolab.accounts.identity import current_user
from polycolab.agents.credentials import credential_from_secret, reserve_file_mutation
from polycolab.app.dependencies import DbSession
from polycolab.db.models.projects import SqlProject
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.projects.default_files import DefaultFiles


@dataclass(frozen=True)
class FileAccess:
    user_id: UUID
    secret: str | None = field(default=None, repr=False)

    def check_key(self, db: Session, project_id: UUID) -> None:
        if self.secret is None:
            return
        key = credential_from_secret(db, self.secret, consume_request=False, allow_project=True)
        if key.sponsor_user_id != self.user_id or (
            key.scope_kind == "PROJECT" and key.project_id != project_id
        ):
            raise ProjectNotFound

    def bind(self, db: Session, files: DefaultFiles, *, write: bool) -> None:
        if self.secret is None:
            return
        if write:
            # Failed or ambiguous filesystem commands retain their reservation.
            reserve_file_mutation(db, self.secret)
        if db.get_bind().dialect.name == "sqlite":
            # SQLite has no row locks. Acquire its writer lock before authorization reads
            # so membership/key revocation cannot commit midway through filesystem I/O.
            db.execute(
                update(SqlProject)
                .where(SqlProject.id == files.project_id)
                .values(updated_at=SqlProject.updated_at)
                .execution_options(synchronize_session=False)
            )
        # Called under the project/membership and filesystem locks, immediately before I/O.
        files.authorize_access = lambda _write: self.check_key(db, files.project_id)


def file_access(
    project_id: UUID, request: Request, response: Response, db: DbSession
) -> FileAccess:
    response.headers["Cache-Control"] = "private, no-store"
    token = bearer_token(request.headers.get("authorization"))
    if token and token.startswith("pca_"):
        key = credential_from_secret(db, token, allow_project=True)
        if key.scope_kind == "PROJECT" and key.project_id != project_id:
            raise ProjectNotFound
        return FileAccess(key.sponsor_user_id, token)
    user = current_user(SqlAlchemyTransaction(db), current_principal(request))
    return FileAccess(user.id)


CurrentFileAccess = Annotated[FileAccess, Depends(file_access)]

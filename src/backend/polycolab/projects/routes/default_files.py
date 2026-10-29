"""Member-only access to the current files in Default projects."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from polycolab.app.dependencies import DbSession
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.default_files import (
    DefaultFileCommand,
    DefaultFileRead,
    DefaultFiles,
    DefaultFilesRead,
)
from polycolab.projects.file_access import CurrentFileAccess

router = APIRouter(prefix="/api/v1/projects/{project_id}/files", tags=["default files"])


def service(settings: Settings, db: Session, project_id: UUID, user_id: UUID) -> DefaultFiles:
    if settings.project_repository_directory is None:
        raise RepositoryError("repository_disabled", 503)
    return DefaultFiles(
        SqlAlchemyTransaction(db),
        settings.project_repository_directory,
        project_id,
        user_id,
        settings.project_repository_max_bytes,
    )


@router.get("", operation_id="getDefaultFiles")
def list_files(
    project_id: UUID, request: Request, db: DbSession, access: CurrentFileAccess
) -> DefaultFilesRead:
    instance = service(request.app.state.settings, db, project_id, access.user_id)
    access.bind(db, instance, write=False)
    with instance.locked(False):
        return instance.listing()


@router.post("", operation_id="changeDefaultFiles")
def command(
    project_id: UUID,
    payload: DefaultFileCommand,
    request: Request,
    db: DbSession,
    access: CurrentFileAccess,
) -> DefaultFileRead | DefaultFilesRead:
    instance = service(request.app.state.settings, db, project_id, access.user_id)
    access.bind(db, instance, write=payload.action not in {"list", "read"})
    return instance.execute(payload)

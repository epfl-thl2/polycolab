"""Member-only access to the current files in Basic projects."""

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from polycolab.app.dependencies import DbSession
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.basic_files import (
    BasicFileCommand,
    BasicFileRead,
    BasicFiles,
    BasicFilesRead,
)
from polycolab.projects.file_access import CurrentFileAccess

router = APIRouter(prefix="/api/v1/projects/{project_id}/files", tags=["default files"])


def service(settings: Settings, db: Session, project_id: UUID, user_id: UUID) -> BasicFiles:
    if settings.project_repository_directory is None:
        raise RepositoryError("repository_disabled", 503)
    return BasicFiles(
        SqlAlchemyTransaction(db),
        settings.project_repository_directory,
        project_id,
        user_id,
        settings.project_repository_max_bytes,
    )


@router.get("", operation_id="getBasicFiles")
def list_files(
    project_id: UUID, request: Request, db: DbSession, access: CurrentFileAccess
) -> BasicFilesRead:
    instance = service(request.app.state.settings, db, project_id, access.user_id)
    access.bind(db, instance, write=False)
    with instance.locked(False):
        return instance.listing()


@router.post("", operation_id="changeBasicFiles")
def command(
    project_id: UUID,
    payload: BasicFileCommand,
    request: Request,
    db: DbSession,
    access: CurrentFileAccess,
) -> BasicFileRead | BasicFilesRead:
    instance = service(request.app.state.settings, db, project_id, access.user_id)
    access.bind(db, instance, write=payload.action not in {"list", "read"})
    return instance.execute(payload)

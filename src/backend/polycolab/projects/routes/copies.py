"""Copy an exact visible Library statement into an editable project object."""

from fastapi import APIRouter, Depends

from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.projects import copies
from polycolab.projects.schemas import ProjectVersionCopyCreate, ProjectVersionCopyRead

router = APIRouter(
    prefix="/api/v1/project-copies", tags=["projects"], dependencies=[Depends(no_store)]
)


@router.post(
    "",
    response_model=ProjectVersionCopyRead,
    status_code=201,
    operation_id="copyLibraryToProject",
)
def create(
    payload: ProjectVersionCopyCreate,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ProjectVersionCopyRead:
    result = copies.create(session, actor=actor, payload=payload.historical_command(), key=key)
    return ProjectVersionCopyRead(
        project_id=result.project_id,
        object_id=result.object_id,
        object_version_id=result.revision_id,
        source_object_version_id=result.source_revision_id,
    )

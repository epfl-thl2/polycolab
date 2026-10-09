"""Copy an exact visible Library statement into an editable workspace object."""

from fastapi import APIRouter, Depends

from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.workspaces import copies
from polycolab.workspaces.schemas import WorkspaceVersionCopyCreate, WorkspaceVersionCopyRead

router = APIRouter(
    prefix="/api/v1/workspace-copies", tags=["workspaces"], dependencies=[Depends(no_store)]
)


@router.post(
    "",
    response_model=WorkspaceVersionCopyRead,
    status_code=201,
    operation_id="copyLibraryToWorkspace",
)
def create(
    payload: WorkspaceVersionCopyCreate, key: RetryKey, session: DbSession, actor: CurrentActor
) -> WorkspaceVersionCopyRead:
    result = copies.create(session, actor=actor, payload=payload.historical_command(), key=key)
    return WorkspaceVersionCopyRead(
        project_id=result.project_id,
        object_id=result.object_id,
        object_version_id=result.revision_id,
        source_object_version_id=result.source_revision_id,
    )

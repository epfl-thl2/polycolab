"""Member-visible saved task working copies, separate from private conversations."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.entities.repositories import RepositoryError
from polycolab.workspaces.repository_service import RepositoryService
from polycolab.workspaces.routes.repository import service
from polycolab.workspaces.task_schemas import (
    WorkspaceTaskCreate,
    WorkspaceTaskRead,
    WorkspaceTaskUpdate,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/tasks", tags=["workspace tasks"])


def task_service(
    request: Request, db: DbSession, workspace_id: UUID, user_id: UUID
) -> RepositoryService:
    if request.app.state.settings.workspace_repository_directory is None:
        raise RepositoryError("task_storage_disabled", 409)
    return service(request, db, workspace_id, user_id)


@router.get("", response_model=list[WorkspaceTaskRead], operation_id="listWorkspaceTasks")
def list_tasks(
    workspace_id: UUID,
    request: Request,
    response: Response,
    page: Page,
    db: DbSession,
    user: CurrentUser,
    include_archived: bool = False,
) -> list[WorkspaceTaskRead]:
    instance = task_service(request, db, workspace_id, user.id)
    instance.authorize()
    return [
        WorkspaceTaskRead.model_validate(value)
        for value in paginated(instance.store.tasks(workspace_id, include_archived), page, response)
    ]


@router.get("/{task_id}", response_model=WorkspaceTaskRead, operation_id="getWorkspaceTask")
def get_task(
    workspace_id: UUID, task_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> WorkspaceTaskRead:
    instance = task_service(request, db, workspace_id, user.id)
    instance.authorize()
    return WorkspaceTaskRead.model_validate(instance.store.task(workspace_id, task_id))


@router.post(
    "", response_model=WorkspaceTaskRead, status_code=201, operation_id="createWorkspaceTask"
)
def create_task(
    workspace_id: UUID,
    payload: WorkspaceTaskCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorkspaceTaskRead:
    return WorkspaceTaskRead.model_validate(
        task_service(request, db, workspace_id, user.id).create_task(
            payload.client_request_id, payload.title
        )
    )


@router.patch("/{task_id}", response_model=WorkspaceTaskRead, operation_id="updateWorkspaceTask")
def update_task(
    workspace_id: UUID,
    task_id: UUID,
    payload: WorkspaceTaskUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorkspaceTaskRead:
    return WorkspaceTaskRead.model_validate(
        task_service(request, db, workspace_id, user.id).update_task(
            task_id, payload.title, payload.archived
        )
    )

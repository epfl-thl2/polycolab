"""Member-visible saved task working copies, separate from private conversations."""

from uuid import UUID

from fastapi import APIRouter, Request, Response

from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.entities.repositories import RepositoryError
from polycolab.projects.repository_service import RepositoryService
from polycolab.projects.routes.repository import service
from polycolab.projects.task_schemas import (
    ProjectTaskCreate,
    ProjectTaskRead,
    ProjectTaskUpdate,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/tasks", tags=["project tasks"])


def task_service(
    request: Request, db: DbSession, project_id: UUID, user_id: UUID
) -> RepositoryService:
    if request.app.state.settings.project_repository_directory is None:
        raise RepositoryError("task_storage_disabled", 409)
    return service(request, db, project_id, user_id)


@router.get("", response_model=list[ProjectTaskRead], operation_id="listProjectTasks")
def list_tasks(
    project_id: UUID,
    request: Request,
    response: Response,
    page: Page,
    db: DbSession,
    user: CurrentUser,
    include_archived: bool = False,
) -> list[ProjectTaskRead]:
    instance = task_service(request, db, project_id, user.id)
    instance.authorize()
    return [
        ProjectTaskRead.model_validate(value)
        for value in paginated(instance.store.tasks(project_id, include_archived), page, response)
    ]


@router.get("/{task_id}", response_model=ProjectTaskRead, operation_id="getProjectTask")
def get_task(
    project_id: UUID, task_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> ProjectTaskRead:
    instance = task_service(request, db, project_id, user.id)
    instance.authorize()
    return ProjectTaskRead.model_validate(instance.store.task(project_id, task_id))


@router.post("", response_model=ProjectTaskRead, status_code=201, operation_id="createProjectTask")
def create_task(
    project_id: UUID,
    payload: ProjectTaskCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ProjectTaskRead:
    return ProjectTaskRead.model_validate(
        task_service(request, db, project_id, user.id).create_task(
            payload.client_request_id, payload.title
        )
    )


@router.patch("/{task_id}", response_model=ProjectTaskRead, operation_id="updateProjectTask")
def update_task(
    project_id: UUID,
    task_id: UUID,
    payload: ProjectTaskUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ProjectTaskRead:
    return ProjectTaskRead.model_validate(
        task_service(request, db, project_id, user.id).update_task(
            task_id, payload.title, payload.archived
        )
    )

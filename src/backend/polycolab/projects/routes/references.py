"""Private references never appear in public projections or backlink counts."""

from uuid import UUID

from fastapi import APIRouter, Depends

from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.projects import references as project_references
from polycolab.research.contracts import (
    ProjectReferenceCreate,
    ProjectReferencePage,
    ProjectReferenceRead,
    ProjectReferenceUpgrade,
)
from polycolab.research.routes.records import Cursor, Limit

router = APIRouter(
    prefix="/api/v1/project-references", tags=["references"], dependencies=[Depends(no_store)]
)


@router.post("", response_model=ProjectReferenceRead, status_code=201, operation_id="workPrivately")
def create(
    payload: ProjectReferenceCreate,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ProjectReferenceRead:
    return project_references.create(session, actor=actor, payload=payload, key=key)


@router.post(
    "/{reference_id}/versions",
    response_model=ProjectReferenceRead,
    operation_id="upgradeProjectReference",
)
def upgrade(
    reference_id: UUID,
    payload: ProjectReferenceUpgrade,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ProjectReferenceRead:
    return project_references.upgrade(
        session, actor=actor, reference_id=reference_id, payload=payload, key=key
    )


@router.get("", response_model=ProjectReferencePage, operation_id="listProjectReferences")
def page(
    project_id: UUID,
    session: DbSession,
    user: CurrentUser,
    reference_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ProjectReferencePage:
    return project_references.page(
        session,
        project_id=project_id,
        user_id=user.id,
        reference_id=reference_id,
        limit=limit,
        cursor=cursor,
    )

"""Private references never appear in public projections or backlink counts."""

from uuid import UUID

from fastapi import APIRouter, Depends

from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.research.contracts import (
    WorkspaceReferenceCreate,
    WorkspaceReferencePage,
    WorkspaceReferenceRead,
    WorkspaceReferenceUpgrade,
)
from polycolab.research.routes.records import Cursor, Limit
from polycolab.workspaces import references as workspace_references

router = APIRouter(
    prefix="/api/v1/workspace-references", tags=["references"], dependencies=[Depends(no_store)]
)


@router.post(
    "", response_model=WorkspaceReferenceRead, status_code=201, operation_id="workPrivately"
)
def create(
    payload: WorkspaceReferenceCreate,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> WorkspaceReferenceRead:
    return workspace_references.create(session, actor=actor, payload=payload, key=key)


@router.post(
    "/{reference_id}/versions",
    response_model=WorkspaceReferenceRead,
    operation_id="upgradeWorkspaceReference",
)
def upgrade(
    reference_id: UUID,
    payload: WorkspaceReferenceUpgrade,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> WorkspaceReferenceRead:
    return workspace_references.upgrade(
        session, actor=actor, reference_id=reference_id, payload=payload, key=key
    )


@router.get("", response_model=WorkspaceReferencePage, operation_id="listWorkspaceReferences")
def page(
    workspace_id: UUID,
    session: DbSession,
    user: CurrentUser,
    reference_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> WorkspaceReferencePage:
    return workspace_references.page(
        session,
        project_id=workspace_id,
        user_id=user.id,
        reference_id=reference_id,
        limit=limit,
        cursor=cursor,
    )

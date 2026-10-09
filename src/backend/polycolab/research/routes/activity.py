"""Bounded authenticated research-attempt and associated-resource APIs."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from polycolab.app.access import Access
from polycolab.app.dependencies import CurrentActor, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.research import activity as research_activity
from polycolab.research import attempts
from polycolab.research.activity_schemas import (
    ResearchCommentVersionPage,
    ResearchCommentVersionRead,
    ResearchCommentVersionWrite,
    ResearchProgressVersionPage,
    ResearchProgressVersionRead,
    ResearchProgressVersionWrite,
    ResearchSummaryVersionPage,
    ResearchSummaryVersionRead,
    ResearchSummaryVersionWrite,
)
from polycolab.research.contracts import (
    HumanNotePage,
    HumanNoteRead,
    HumanNoteWrite,
    ResearchCommentPage,
    ResearchCommentRead,
    ResearchCommentWrite,
    ResearchProgressPage,
    ResearchProgressRead,
    ResearchProgressWrite,
    ResearchSummaryPage,
    ResearchSummaryRead,
)
from polycolab.research.read_access import collection_scope
from polycolab.research.version_schemas import ObjectVersionPage

router = APIRouter(prefix="/api/v1", tags=["research"], dependencies=[Depends(no_store)])
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]


@router.get(
    "/research/objects/{object_id}/attempts",
    response_model=ObjectVersionPage,
    operation_id="listScopedResearchAttempts",
)
def scoped_attempts(
    object_id: UUID,
    session: DbSession,
    access: Access,
    workspace_id: UUID | None = None,
    scope: Literal["public", "member"] = "public",
    target_object_version_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ObjectVersionPage:
    workspace_id = collection_scope(session, access, scope, workspace_id)
    return attempts.history(
        session,
        target_object_id=object_id,
        target_revision_id=target_object_version_id,
        project_id=workspace_id,
        limit=limit,
        cursor=cursor,
    )


@router.put(
    "/research/objects/{object_id}/human-note",
    response_model=HumanNoteRead,
    operation_id="writeResearchHumanNote",
)
def write_human_note(
    object_id: UUID,
    payload: HumanNoteWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> HumanNoteRead:
    return research_activity.write_human_note(
        session, actor=actor, object_id=object_id, payload=payload, key=key
    )


@router.get(
    "/research/objects/{object_id}/human-note",
    response_model=HumanNoteRead,
    operation_id="getResearchHumanNote",
)
def get_human_note(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
) -> HumanNoteRead:
    return research_activity.get_human_note(
        session, actor=actor, object_id=object_id, project_id=workspace_id
    )


@router.get(
    "/research/objects/{object_id}/human-note/history",
    response_model=HumanNotePage,
    operation_id="listResearchHumanNoteHistory",
)
def human_note_history(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> HumanNotePage:
    return research_activity.human_note_history(
        session,
        actor=actor,
        object_id=object_id,
        project_id=workspace_id,
        limit=limit,
        cursor=cursor,
    )


@router.put(
    "/research/objects/{object_id}/summary",
    response_model=ResearchSummaryVersionRead,
    operation_id="writeResearchSummary",
)
def write_summary(
    object_id: UUID,
    payload: ResearchSummaryVersionWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ResearchSummaryRead:
    return research_activity.write_summary(
        session, actor=actor, object_id=object_id, payload=payload.historical_command(), key=key
    )


@router.get(
    "/research/objects/{object_id}/summary",
    response_model=ResearchSummaryVersionRead,
    operation_id="getResearchSummary",
)
def get_summary(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
) -> ResearchSummaryRead:
    return research_activity.get_summary(
        session, actor=actor, object_id=object_id, project_id=workspace_id
    )


@router.get(
    "/research/objects/{object_id}/summary/history",
    response_model=ResearchSummaryVersionPage,
    operation_id="listResearchSummaryHistory",
)
def summary_history(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ResearchSummaryPage:
    return research_activity.summary_history(
        session,
        actor=actor,
        object_id=object_id,
        project_id=workspace_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/research/objects/{object_id}/progress",
    response_model=ResearchProgressVersionRead,
    status_code=201,
    operation_id="reportResearchProgress",
)
def report_progress(
    object_id: UUID,
    payload: ResearchProgressVersionWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ResearchProgressRead:
    return research_activity.write_progress(
        session,
        actor=actor,
        object_id=object_id,
        payload=ResearchProgressWrite(
            project_id=payload.project_id,
            revision_id=payload.object_version_id,
            status=payload.status,
            detail_md=payload.detail_md,
        ),
        key=key,
    )


@router.get(
    "/research/objects/{object_id}/progress",
    response_model=ResearchProgressVersionPage,
    operation_id="listResearchProgress",
)
def progress_history(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
    object_version_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ResearchProgressPage:
    return research_activity.progress_history(
        session,
        actor=actor,
        object_id=object_id,
        project_id=workspace_id,
        revision_id=object_version_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/research/objects/{object_id}/comments",
    response_model=ResearchCommentVersionRead,
    status_code=201,
    operation_id="commentOnResearchVersion",
)
def write_comment(
    object_id: UUID,
    payload: ResearchCommentVersionWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> ResearchCommentRead:
    return research_activity.write_comment(
        session,
        actor=actor,
        object_id=object_id,
        payload=ResearchCommentWrite(
            project_id=payload.project_id,
            revision_id=payload.object_version_id,
            body_md=payload.body_md,
        ),
        key=key,
    )


@router.get(
    "/research/objects/{object_id}/comments",
    response_model=ResearchCommentVersionPage,
    operation_id="listResearchComments",
)
def comment_history(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    workspace_id: UUID | None = None,
    object_version_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ResearchCommentPage:
    return research_activity.comment_history(
        session,
        actor=actor,
        object_id=object_id,
        project_id=workspace_id,
        revision_id=object_version_id,
        limit=limit,
        cursor=cursor,
    )

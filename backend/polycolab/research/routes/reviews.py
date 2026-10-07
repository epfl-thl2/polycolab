"""Authorized exact-version reviews and bounded map summaries."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import and_, or_, select

from polycolab.access.actors import Actor
from polycolab.app.access import Access
from polycolab.app.dependencies import DbSession
from polycolab.db.models import SqlContributionEnvelope, SqlObjectRevision, SqlResearchScope
from polycolab.db.models.reviews import SqlObjectReview
from polycolab.research import reviews
from polycolab.research.assurance import _decode_cursor, _encode_cursor
from polycolab.research.direct import MutationResult, OutputRead, mutate
from polycolab.research.objects import ResearchNotFound
from polycolab.research.read_access import revision_scope
from polycolab.research.records import project_access, read_condition
from polycolab.research.review_schemas import ReviewBatch, ReviewPage, ReviewSummary, ReviewWrite
from polycolab.research.routes.direct import RetryKey

router = APIRouter(prefix="/api/v1", tags=["reviews"])


@router.post(
    "/reviews", response_model=MutationResult, status_code=201, operation_id="reviewObjectVersion"
)
def create_review(
    payload: ReviewWrite, session: DbSession, access: Access, key: RetryKey
) -> MutationResult:
    workspace_id = revision_scope(session, access, payload.object_version_id)
    revision = session.get(SqlObjectRevision, payload.object_version_id)
    if revision is None:
        raise ResearchNotFound
    # A public reader reviews in the public commons, not in a private source workspace.
    scope = session.scalar(
        select(SqlResearchScope).where(
            SqlResearchScope.project_id == workspace_id
            if workspace_id
            else SqlResearchScope.scope_kind == "COMMONS"
        )
    )
    if scope is None:
        raise ResearchNotFound

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        saved = reviews.write(session, actor=actor, payload=payload, contribution=envelope)
        return [OutputRead(entity_type="OBJECT_REVIEW", entity_id=saved.id)]

    return mutate(session, access, scope, "review", key, payload.model_dump(mode="json"), apply)


@router.get(
    "/reviews/{object_version_id}",
    response_model=ReviewPage,
    operation_id="listObjectVersionReviews",
)
def history(
    object_version_id: UUID,
    session: DbSession,
    access: Access,
    workspace_id: UUID | None = None,
    current: bool = False,
    workspace_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> ReviewPage:
    scope = revision_scope(session, access, object_version_id, workspace_id)
    query = (
        reviews.current_query([object_version_id], scope)
        if current
        else select(SqlObjectReview).where(
            SqlObjectReview.object_version_id == object_version_id, reviews.visible_condition(scope)
        )
    )
    if workspace_only:
        if workspace_id is None or scope is None:
            raise ResearchNotFound
        query = query.where(
            SqlObjectReview.ownership_scope_id.in_(
                select(SqlResearchScope.id).where(SqlResearchScope.project_id == workspace_id)
            )
        )
    if cursor:
        created_at, _, row_id = _decode_cursor(cursor)
        query = query.where(
            or_(
                SqlObjectReview.created_at > created_at,
                and_(SqlObjectReview.created_at == created_at, SqlObjectReview.id > row_id),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(SqlObjectReview.created_at, SqlObjectReview.id).limit(limit + 1)
        )
    )
    return ReviewPage(
        items=[
            reviews.read(row).model_copy(
                update={
                    "is_mine": bool(access.user and row.reviewer_id == f"human:{access.user.id}")
                }
            )
            for row in rows[:limit]
        ],
        next_cursor=_encode_cursor(rows[limit - 1].created_at, "endorsement", rows[limit - 1].id)
        if len(rows) > limit
        else None,
    )


@router.post(
    "/reviews/summary",
    response_model=list[ReviewSummary],
    operation_id="summarizeObjectVersionReviews",
)
def summary(
    payload: ReviewBatch, session: DbSession, access: Access, workspace_id: UUID | None = None
) -> list[ReviewSummary]:
    if workspace_id:
        project_access(session, workspace_id, access.require_user_id())
    visible = set(
        session.scalars(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.id.in_(payload.object_version_ids), read_condition(workspace_id)
            )
        )
    )
    if visible != set(payload.object_version_ids):
        raise ResearchNotFound
    return reviews.summaries(session, payload.object_version_ids, workspace_id)

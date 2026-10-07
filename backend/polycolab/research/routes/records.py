"""Bounded typed research APIs sharing scope policy with hosted tools."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased

from polycolab.app.access import Access
from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession
from polycolab.catalogue.routes.catalogue import RetryKey, no_store
from polycolab.db.models import SqlObjectRevision, SqlRelationAssertion, SqlResearchScope
from polycolab.research import records
from polycolab.research.contracts import (
    CorrectionDecisionRead,
    CorrectionDecisionWrite,
    ObjectVersionDisplayBatchRead,
    ObjectVersionDisplayRequest,
    RecordModerationRead,
    RecordModerationWrite,
)
from polycolab.research.read_access import collection_scope, revision_scope
from polycolab.research.version_projections import (
    projected_version_reads,
    relationship_reads,
    version_reads,
)
from polycolab.research.version_schemas import (
    ObjectVersionPage,
    ObjectVersionRead,
    ObjectVersionRelationshipRead,
)

router = APIRouter(prefix="/api/v1", tags=["records"], dependencies=[Depends(no_store)])
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=200)]


@router.post(
    "/records/objects/{object_id}/moderation",
    response_model=RecordModerationRead,
    operation_id="moderatePublicRecord",
)
def moderate_record(
    object_id: UUID,
    payload: RecordModerationWrite,
    key: RetryKey,
    session: DbSession,
    actor: CurrentActor,
) -> RecordModerationRead:
    from polycolab.catalogue.moderation import moderate

    return moderate(session, actor=actor, object_id=object_id, payload=payload, key=key)


@router.get(
    "/records/objects/{object_id}/moderation",
    response_model=list[RecordModerationRead],
    operation_id="listPublicRecordModerationAudit",
)
def record_moderation_history(
    object_id: UUID,
    session: DbSession,
    actor: CurrentActor,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> list[RecordModerationRead]:
    from polycolab.catalogue.moderation import history

    return history(
        session,
        actor=actor,
        object_id=object_id,
        limit=limit,
        after=records.decode_cursor(cursor) if cursor else None,
    )


@router.post(
    "/records/{object_version_id}/decision",
    response_model=CorrectionDecisionRead,
    operation_id="decidePublicCorrection",
)
def decide_correction(
    object_version_id: UUID,
    payload: CorrectionDecisionWrite,
    key: RetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> CorrectionDecisionRead:
    from polycolab.catalogue.corrections import decide

    return decide(
        session,
        actor=actor,
        settings=request.app.state.settings,
        revision_id=object_version_id,
        payload=payload,
        key=key,
    )


@router.get(
    "/records/{object_version_id}/decision",
    response_model=CorrectionDecisionRead | None,
    operation_id="getPublicCorrectionDecision",
)
def correction_decision(
    object_version_id: UUID, session: DbSession, access: Access
) -> CorrectionDecisionRead | None:
    from polycolab.catalogue.corrections import decision_read
    from polycolab.db.models import SqlCorrectionDecision

    records.public_revision(session, object_version_id)
    value = session.get(SqlCorrectionDecision, object_version_id)
    return decision_read(value) if value else None


@router.get("/records", response_model=ObjectVersionPage, operation_id="listWorkspaceRecords")
def list_private(
    session: DbSession,
    access: Access,
    workspace_id: UUID | None = None,
    scope: Literal["public", "member"] = "public",
    statement_id: UUID | None = None,
    object_id: UUID | None = None,
    limit: Limit = 25,
    cursor: Cursor = None,
) -> ObjectVersionPage:
    workspace_id = collection_scope(session, access, scope, workspace_id)
    selected = records.list_records(
        session,
        project_id=workspace_id,
        statement_id=statement_id,
        object_id=object_id,
        limit=limit,
        cursor=cursor,
    )
    rows = {
        row.id: row
        for row in session.scalars(
            select(SqlObjectRevision).where(
                SqlObjectRevision.id.in_([item.revision_id for item in selected.items])
            )
        )
    }
    return ObjectVersionPage(
        items=projected_version_reads(
            session,
            [rows[item.revision_id] for item in selected.items],
            selected.items,
            public=workspace_id is None,
        ),
        next_cursor=selected.next_cursor,
    )


@router.get(
    "/records/{object_version_id}", response_model=ObjectVersionRead, operation_id="getScopedRecord"
)
def private_detail(
    object_version_id: UUID, session: DbSession, access: Access, workspace_id: UUID | None = None
) -> ObjectVersionRead:
    workspace_id = revision_scope(session, access, object_version_id, workspace_id)
    row = records.accessible_revision(session, object_version_id, workspace_id)
    return version_reads(session, [row], project_id=workspace_id, public=workspace_id is None)[0]


@router.post(
    "/research/versions/display",
    response_model=ObjectVersionDisplayBatchRead,
    operation_id="resolveResearchObjectVersionDisplays",
)
def object_version_displays(
    payload: ObjectVersionDisplayRequest, session: DbSession, user: CurrentUser
) -> ObjectVersionDisplayBatchRead:
    if payload.project_id is not None:
        records.project_access(session, payload.project_id, user.id)
    return records.object_version_displays(session, payload)


def relations(
    session: DbSession,
    revision_id: UUID,
    workspace_id: UUID | None,
    limit: int,
    cursor: str | None,
    response: Response,
) -> list[ObjectVersionRelationshipRead]:
    records.accessible_revision(session, revision_id, workspace_id)
    source = aliased(SqlObjectRevision)
    target = aliased(SqlObjectRevision)
    predicate = records.public_condition(source.id)
    target_predicate = records.public_condition(target.id)
    if workspace_id is not None:
        predicate = or_(source.project_id == workspace_id, predicate)
        target_predicate = or_(target.project_id == workspace_id, target_predicate)
    query = (
        select(SqlRelationAssertion)
        .join(source, source.id == SqlRelationAssertion.source_revision_id)
        .join(target, target.id == SqlRelationAssertion.target_revision_id)
        .where(
            predicate,
            target_predicate,
            or_(source.id == revision_id, target.id == revision_id),
            records.relation_read_condition(workspace_id),
        )
        .order_by(SqlRelationAssertion.id)
    )
    if cursor is not None:
        query = query.where(SqlRelationAssertion.id > records.decode_cursor(cursor))
    values = list(session.scalars(query.limit(limit + 1)))
    if len(values) > limit:
        response.headers["X-Next-Cursor"] = records.encode_cursor(values[limit - 1].id)
    selected = values[:limit]
    declaring_scope_id = (
        session.scalar(
            select(SqlResearchScope.id).where(SqlResearchScope.project_id == workspace_id)
        )
        if workspace_id is not None
        else None
    )
    private_ids = [
        row.id
        for row in selected
        if declaring_scope_id is not None and row.ownership_scope_id == declaring_scope_id
    ]
    public_ids = [row.id for row in selected if row.id not in private_ids]
    projected = {
        row.id: row
        for row in [
            *relationship_reads(session, private_ids, public=False),
            *relationship_reads(session, public_ids, public=True),
        ]
    }
    return [projected[row.id] for row in selected]


@router.get(
    "/versions/{object_version_id}/relationships",
    response_model=list[ObjectVersionRelationshipRead],
    operation_id="listScopedRecordRelations",
)
def private_relations(
    object_version_id: UUID,
    session: DbSession,
    access: Access,
    response: Response,
    workspace_id: UUID | None = None,
    limit: Limit = 50,
    cursor: Cursor = None,
) -> list[ObjectVersionRelationshipRead]:
    if workspace_id is None:
        workspace_id = revision_scope(session, access, object_version_id)
    else:
        # A declaring workspace can connect public versions it does not own.
        records.project_access(session, workspace_id, access.require_user_id())
    return relations(session, object_version_id, workspace_id, limit, cursor, response)

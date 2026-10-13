"""Shared independently attributable research mutations and exact-source reads."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from polycolab.access.actors import Actor
from polycolab.app.access import Access
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import DbSession
from polycolab.db.models import (
    CanonicalEntityType,
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlProject,
    SqlResearchActivityEvent,
    SqlResearchAttachment,
    SqlResearchObject,
    SqlResearchProgressUpdate,
    SqlResearchScope,
    SqlResearchSummary,
    SqlResearchSummaryRevision,
)
from polycolab.platform.outbox import canonical_digest
from polycolab.research import activity, records
from polycolab.research.activity_schemas import (
    ResearchProgressVersionPage,
    ResearchProgressVersionWrite,
    ResearchSummaryVersionRead,
    ResearchSummaryVersionWrite,
)
from polycolab.research.contracts import (
    ResearchCommentWrite,
    ResearchProgressPage,
    ResearchProgressWrite,
    ResearchSummaryRead,
    SnapshotRelationWrite,
)
from polycolab.research.contributions import link_output
from polycolab.research.direct import (
    LibraryDestination,
    MutationResult,
    OutputRead,
    authorize,
    destination_scope,
    mutate,
    require_edit_author,
)
from polycolab.research.objects import ResearchNotFound
from polycolab.research.routes.core import member, object_scope, project
from polycolab.research.version_commands import snapshot_command
from polycolab.research.version_projections import version_reads
from polycolab.research.version_schemas import (
    BidirectionalDeclarationCreate,
    ObjectVersionCommentCreate,
    ObjectVersionCreate,
    ObjectVersionDeclarationCreate,
    ObjectVersionRead,
    VersionedObjectCreate,
    VersionLibraryDestination,
)

router = APIRouter(prefix="/api/v1", tags=["research"])
RetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def scoped_object(
    session: DbSession, access: Access, object_id: UUID
) -> tuple[SqlResearchObject, SqlResearchScope]:
    obj, _ = object_scope(session, access, object_id)
    scope = session.get(SqlResearchScope, obj.ownership_scope_id)
    if scope is None:
        raise ResearchNotFound
    return obj, scope


@router.post(
    "/objects", response_model=MutationResult, status_code=201, operation_id="createResearchObject"
)
def create(
    payload: VersionedObjectCreate, session: DbSession, access: Access, key: RetryKey
) -> MutationResult:
    from polycolab.research.direct import ProjectDestination

    destination = (
        LibraryDestination(
            kind="library", statement_revision_id=payload.destination.statement_object_version_id
        )
        if isinstance(payload.destination, VersionLibraryDestination)
        else ProjectDestination(kind="project", project_id=payload.destination.project_id)
    )
    scope = destination_scope(session, destination)
    try:
        data = snapshot_command(payload.snapshot, project_id=scope.project_id)
        if payload.catalogue_suggestion is not None:
            from polycolab.catalogue.schemas import CatalogueRevise

            proposal = payload.catalogue_suggestion
            data.suggestion = CatalogueRevise(
                **proposal.model_dump(exclude={"expected_current_object_version_id"}),
                base_revision_id=proposal.expected_current_object_version_id,
            )
    except ValidationError:
        raise HTTPException(422, "invalid_research_structure") from None
    if (
        isinstance(payload.destination, VersionLibraryDestination)
        and payload.destination.statement_object_version_id not in data.statement_revision_ids
    ):
        raise HTTPException(422, "library_destination_requires_explicit_attachment")

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        result = records.write_record(
            session,
            actor=actor,
            payload=data,
            key=canonical_digest(["direct.object.create", key]),
            contribution=envelope,
            commit=False,
        )
        assert result.revision_id
        return [
            OutputRead(entity_type="RESEARCH_OBJECT", entity_id=result.id),
            OutputRead(entity_type="OBJECT_REVISION", entity_id=result.revision_id),
        ]

    return mutate(
        session, access, scope, "object.create", key, payload.model_dump(mode="json"), apply
    )


@router.post(
    "/objects/{object_id}/versions",
    response_model=MutationResult,
    status_code=201,
    operation_id="createObjectVersion",
)
def revise(
    object_id: UUID, payload: ObjectVersionCreate, session: DbSession, access: Access, key: RetryKey
) -> MutationResult:
    obj, scope = scoped_object(session, access, object_id)
    actor = authorize(session, access, scope)
    require_edit_author(session, actor, obj)
    base = session.get(SqlObjectRevision, payload.expected_current_object_version_id)
    if base is None or base.object_id != obj.id:
        raise ResearchNotFound
    try:
        data = snapshot_command(
            payload.snapshot,
            project_id=scope.project_id,
            object_id=obj.id,
            expected_current_object_version_id=base.id,
        )
    except ValidationError:
        raise HTTPException(422, "invalid_research_structure") from None

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        result = records.write_record(
            session,
            actor=actor,
            payload=data,
            key=canonical_digest(["direct.object.revise", key]),
            contribution=envelope,
            commit=False,
        )
        assert result.revision_id
        return [OutputRead(entity_type="OBJECT_REVISION", entity_id=result.revision_id)]

    return mutate(
        session,
        access,
        scope,
        "object.revise",
        key,
        {"object_id": str(obj.id), **payload.model_dump(mode="json")},
        apply,
    )


@router.post(
    "/objects/{object_id}/comments",
    response_model=MutationResult,
    status_code=201,
    operation_id="createObjectComment",
)
def comment(
    object_id: UUID,
    payload: ObjectVersionCommentCreate,
    session: DbSession,
    access: Access,
    key: RetryKey,
) -> MutationResult:
    obj, scope = scoped_object(session, access, object_id)
    target = records.accessible_revision(session, payload.object_version_id, scope.project_id)
    if target.object_id != obj.id:
        raise ResearchNotFound

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        result = activity.write_comment(
            session,
            actor=actor,
            object_id=obj.id,
            payload=ResearchCommentWrite(
                project_id=scope.project_id,
                revision_id=payload.object_version_id,
                body_md=payload.body_md,
            ),
            key=canonical_digest(["direct.comment.create", key]),
            contribution=envelope,
            commit=False,
        )
        link_output(
            session,
            envelope=envelope,
            entity_type=CanonicalEntityType.RESEARCH_COMMENT,
            entity_id=result.id,
            scope_id=scope.id,
        )
        return [OutputRead(entity_type="RESEARCH_COMMENT", entity_id=result.id)]

    return mutate(
        session,
        access,
        scope,
        "comment.create",
        key,
        {"object_id": str(obj.id), **payload.model_dump(mode="json")},
        apply,
    )


@router.post(
    "/relations",
    response_model=MutationResult,
    status_code=201,
    operation_id="createObjectRelation",
)
def relation(
    payload: ObjectVersionDeclarationCreate, session: DbSession, access: Access, key: RetryKey
) -> MutationResult:
    from polycolab.research.direct import ProjectDestination

    destination = (
        LibraryDestination(
            kind="library", statement_revision_id=payload.destination.statement_object_version_id
        )
        if isinstance(payload.destination, VersionLibraryDestination)
        else ProjectDestination(kind="project", project_id=payload.destination.project_id)
    )
    scope = destination_scope(session, destination)
    source_id, target_id = (
        (payload.first_object_version_id, payload.second_object_version_id)
        if isinstance(payload, BidirectionalDeclarationCreate)
        else (payload.source_object_version_id, payload.target_object_version_id)
    )
    authorize(session, access, scope)
    records.accessible_revision(session, source_id, scope.project_id)
    records.accessible_revision(session, target_id, scope.project_id)

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        result = records.write_relation(
            session,
            actor=actor,
            payload=SnapshotRelationWrite(
                project_id=scope.project_id,
                source_revision_id=source_id,
                target_revision_id=target_id,
                relation_type=payload.relationship_type,
                rationale=payload.description or "Declared relationship",
                description=payload.description,
            ),
            key=canonical_digest(["direct.relation.create", key]),
            contribution=envelope,
            commit=False,
        )
        return [OutputRead(entity_type="RELATION_ASSERTION", entity_id=result.id)]

    return mutate(
        session, access, scope, "relation.create", key, payload.model_dump(mode="json"), apply
    )


@router.get(
    "/versions/{object_version_id}",
    response_model=ObjectVersionRead,
    operation_id="getObjectVersion",
)
def revision(object_version_id: UUID, session: DbSession, access: Access) -> ObjectVersionRead:
    row = session.get(SqlObjectRevision, object_version_id)
    if row is None:
        raise ResearchNotFound
    if row.project_id and member(session, access, row.project_id):
        project(session, access, row.project_id)
        return version_reads(session, [row], project_id=row.project_id, public=False)[0]
    return version_reads(session, [row], public=True)[0]


@router.get(
    "/objects/{object_id}/contributions",
    response_model=Collection[ObjectVersionRead],
    operation_id="listAttachedContributions",
)
def contributions(
    object_id: UUID,
    session: DbSession,
    access: Access,
    page: Pagination,
    statement_object_version_id: UUID | None = None,
) -> Collection[ObjectVersionRead]:
    object_scope(session, access, object_id)
    targets = select(SqlObjectRevision.id).where(SqlObjectRevision.object_id == object_id)
    query = (
        select(SqlObjectRevision)
        .join(SqlResearchAttachment, SqlResearchAttachment.revision_id == SqlObjectRevision.id)
        .where(SqlResearchAttachment.statement_revision_id.in_(targets))
    )
    if statement_object_version_id:
        query = query.where(
            SqlResearchAttachment.statement_revision_id == statement_object_version_id
        )
    query = query.where(
        records.public_condition(SqlObjectRevision.id)
        | (
            access.member_condition(SqlObjectRevision.project_id)
            & SqlObjectRevision.project_id.in_(
                select(SqlProject.id).where(SqlProject.deleted_at.is_(None))
            )
        )
    ).distinct()
    rows, cursor = page.select(
        session,
        query,
        SqlObjectRevision.id,
        scope=f"attached:{access.user_id}:{object_id}:{statement_object_version_id}",
    )
    return Collection(
        items=[revision(row.id, session, access) for row in rows],
        next_cursor=cursor,
    )


@router.put(
    "/objects/{object_id}/summary", response_model=MutationResult, operation_id="saveObjectSummary"
)
def save_summary(
    object_id: UUID,
    payload: ResearchSummaryVersionWrite,
    session: DbSession,
    access: Access,
    key: RetryKey,
) -> MutationResult:
    _, scope = scoped_object(session, access, object_id)
    if payload.project_id is not None and payload.project_id != scope.project_id:
        raise ResearchNotFound
    for source_id in payload.source_object_version_ids:
        records.accessible_revision(session, source_id, scope.project_id)
    historical = payload.historical_command()
    data = historical.model_copy(update={"project_id": scope.project_id})

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        saved = activity.write_summary(
            session,
            actor=actor,
            object_id=object_id,
            payload=data,
            key=canonical_digest(["direct.summary", key]),
            contribution=envelope,
            commit=False,
        )
        return [OutputRead(entity_type="SUMMARY_REVISION", entity_id=saved.current_revision.id)]

    return mutate(
        session,
        access,
        scope,
        "summary.write",
        key,
        {"object_id": str(object_id), **historical.model_dump(mode="json")},
        apply,
    )


@router.get(
    "/objects/{object_id}/summary",
    response_model=ResearchSummaryVersionRead,
    operation_id="readObjectSummary",
)
def read_summary(object_id: UUID, session: DbSession, access: Access) -> ResearchSummaryRead:
    from polycolab.research.history import visible_query

    _, private = object_scope(session, access, object_id)
    event = session.scalar(
        visible_query(access, "member" if private else "public")
        .where(
            SqlResearchActivityEvent.object_id == object_id,
            SqlResearchActivityEvent.source_kind == "ResearchSummaryRevision",
        )
        .order_by(SqlResearchActivityEvent.occurred_at.desc(), SqlResearchActivityEvent.id.desc())
        .limit(1)
    )
    summary = session.get(SqlResearchSummary, object_id)
    saved = session.get(SqlResearchSummaryRevision, event.source_id) if event else None
    if summary is None or saved is None:
        raise ResearchNotFound
    scope = session.get(SqlResearchScope, event.ownership_scope_id)
    return activity._summary_read(
        session, summary, saved, scope.project_id if private and scope else None
    )


@router.post(
    "/objects/{object_id}/progress",
    response_model=MutationResult,
    status_code=201,
    operation_id="reportObjectProgress",
)
def report_progress(
    object_id: UUID,
    payload: ResearchProgressVersionWrite,
    session: DbSession,
    access: Access,
    key: RetryKey,
) -> MutationResult:
    _, scope = scoped_object(session, access, object_id)
    if payload.project_id is not None and payload.project_id != scope.project_id:
        raise ResearchNotFound
    target = records.accessible_revision(session, payload.object_version_id, scope.project_id)
    if target.object_id != object_id:
        raise ResearchNotFound
    historical = ResearchProgressWrite(
        project_id=payload.project_id,
        revision_id=payload.object_version_id,
        status=payload.status,
        detail_md=payload.detail_md,
    )
    data = historical.model_copy(update={"project_id": scope.project_id})

    def apply(actor: Actor, envelope: SqlContributionEnvelope) -> list[OutputRead]:
        saved = activity.write_progress(
            session,
            actor=actor,
            object_id=object_id,
            payload=data,
            key=canonical_digest(["direct.progress", key]),
            contribution=envelope,
            commit=False,
        )
        return [OutputRead(entity_type="PROGRESS_UPDATE", entity_id=saved.id)]

    return mutate(
        session,
        access,
        scope,
        "progress.report",
        key,
        {"object_id": str(object_id), **historical.model_dump(mode="json")},
        apply,
    )


@router.get(
    "/objects/{object_id}/progress",
    response_model=ResearchProgressVersionPage,
    operation_id="readObjectProgress",
)
def read_progress(
    object_id: UUID,
    session: DbSession,
    access: Access,
    page: Pagination,
    object_version_id: UUID | None = None,
) -> ResearchProgressPage:
    from polycolab.research.history import visible_query

    _, private = object_scope(session, access, object_id)
    events = (
        visible_query(access, "member" if private else "public")
        .where(
            SqlResearchActivityEvent.object_id == object_id,
            SqlResearchActivityEvent.source_kind == "ResearchProgressUpdate",
        )
        .with_only_columns(SqlResearchActivityEvent.source_id)
    )
    query = select(SqlResearchProgressUpdate).where(SqlResearchProgressUpdate.id.in_(events))
    if object_version_id:
        query = query.where(SqlResearchProgressUpdate.revision_id == object_version_id)
    rows, cursor = page.select(
        session,
        query,
        SqlResearchProgressUpdate.id,
        scope=f"progress:{access.user_id}:{object_id}:{object_version_id}",
    )
    return ResearchProgressPage(
        items=[activity._progress_read(session, row) for row in rows], next_cursor=cursor
    )

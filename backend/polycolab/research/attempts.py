"""Exact-target research attempts, distinct from target edits and job retries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlAttemptEvidenceLink,
    SqlObjectRevision,
    SqlResearchAttemptRevision,
    SqlResearchObject,
)
from polycolab.db.models.research import SqlResearchAttemptMetadata
from polycolab.db.stores.relationships import add_structural_relationship
from polycolab.entities.enums import ResearchObjectKind
from polycolab.entities.research import StructuralRole
from polycolab.research.contracts import (
    AttemptEvidenceRead,
    ResearchAttemptStructureRead,
)
from polycolab.research.schemas import ResearchAttemptRequest
from polycolab.research.version_schemas import ObjectVersionPage
from polycolab.workspaces.service import DomainConflict


def require_structure(kind: ResearchObjectKind, payload: ResearchAttemptRequest | None) -> None:
    if (kind is ResearchObjectKind.ATTEMPT) != (payload is not None):
        raise DomainConflict("attempt structure is required exactly for attempt records")


def validate_structure(
    session: Session,
    *,
    project_id: UUID | None,
    payload: ResearchAttemptRequest,
    existing_attempt_object: SqlResearchObject | None = None,
) -> SqlObjectRevision:
    from polycolab.research.records import accessible_revision

    target = accessible_revision(session, payload.target_revision_id, project_id)
    target_object = session.get(SqlResearchObject, target.object_id)
    if target_object is None or target_object.kind is ResearchObjectKind.ATTEMPT:
        raise DomainConflict("attempts cannot target attempts")
    if existing_attempt_object is not None:
        prior_target = session.scalar(
            select(SqlResearchAttemptRevision.target_object_id)
            .join(
                SqlObjectRevision,
                SqlObjectRevision.id == SqlResearchAttemptRevision.revision_id,
            )
            .where(SqlObjectRevision.object_id == existing_attempt_object.id)
            .order_by(SqlObjectRevision.number)
            .limit(1)
        )
        if prior_target is not None and prior_target != target.object_id:
            raise DomainConflict("an attempt cannot change its target object")
    if payload.result_revision_id is not None:
        result = accessible_revision(session, payload.result_revision_id, project_id)
        if result.object_id != target.object_id or result.number <= target.number:
            raise DomainConflict("attempt result must be a newer target revision")
    for item in payload.evidence:
        accessible_revision(session, item.revision_id, project_id)
    return target


def add_structure(
    session: Session,
    *,
    revision_id: UUID,
    target: SqlObjectRevision,
    payload: ResearchAttemptRequest,
    positions: list[int] | None = None,
) -> SqlResearchAttemptRevision:
    attempt = SqlResearchAttemptMetadata(
        revision_id=revision_id,
        outcome=payload.outcome,
        findings_md=payload.findings_md,
    )
    session.add(attempt)
    session.flush()
    add_structural_relationship(
        session,
        source_object_version_id=revision_id,
        target_object_version_id=target.id,
        relationship_type=StructuralRole.TARGET,
    )
    if payload.result_revision_id is not None:
        add_structural_relationship(
            session,
            source_object_version_id=revision_id,
            target_object_version_id=payload.result_revision_id,
            relationship_type=StructuralRole.RESULT,
        )
    for position, item in enumerate(payload.evidence):
        add_structural_relationship(
            session,
            source_object_version_id=revision_id,
            target_object_version_id=item.revision_id,
            relationship_type=StructuralRole.EVIDENCE,
            evidence_role=item.role,
            position=positions[position] if positions is not None else position,
        )
    session.flush()
    result = session.get(SqlResearchAttemptRevision, revision_id)
    assert result is not None
    return result


def structure_read(
    session: Session, revision_id: UUID, project_id: UUID | None
) -> ResearchAttemptStructureRead | None:
    from polycolab.research.records import accessible_revision

    attempt = session.get(SqlResearchAttemptRevision, revision_id)
    if attempt is None:
        return None
    evidence = list(
        session.scalars(
            select(SqlAttemptEvidenceLink)
            .where(SqlAttemptEvidenceLink.attempt_revision_id == revision_id)
            .order_by(SqlAttemptEvidenceLink.position)
        )
    )
    for dependency_id in [
        attempt.target_revision_id,
        *[item.evidence_revision_id for item in evidence],
        *([attempt.result_revision_id] if attempt.result_revision_id else []),
    ]:
        accessible_revision(session, dependency_id, project_id)
    return ResearchAttemptStructureRead(
        attempt_revision_id=revision_id,
        target_object_id=attempt.target_object_id,
        target_revision_id=attempt.target_revision_id,
        outcome=attempt.outcome,
        findings_md=attempt.findings_md,
        evidence=[
            AttemptEvidenceRead(revision_id=item.evidence_revision_id, role=item.role)
            for item in evidence
        ],
        result_revision_id=attempt.result_revision_id,
    )


def history(
    session: Session,
    *,
    target_object_id: UUID,
    target_revision_id: UUID | None,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> ObjectVersionPage:
    from polycolab.research.records import (
        accessible_revision,
        decode_cursor,
        encode_cursor,
        read_condition,
    )
    from polycolab.research.version_projections import version_reads

    target_object = session.get(SqlResearchObject, target_object_id)
    if target_object is None:
        from polycolab.research.objects import ResearchNotFound

        raise ResearchNotFound
    # An omitted pin requests history across visible target versions. The actual
    # head may be private, so establish access using the latest visible version.
    selected_target = target_revision_id
    if selected_target is None:
        selected_target = session.scalar(
            select(SqlObjectRevision.id)
            .where(SqlObjectRevision.object_id == target_object_id, read_condition(project_id))
            .order_by(SqlObjectRevision.number.desc())
            .limit(1)
        )
    if selected_target is None:
        from polycolab.research.objects import ResearchNotFound

        raise ResearchNotFound
    target = accessible_revision(session, selected_target, project_id)
    if target.object_id != target_object_id:
        from polycolab.research.objects import ResearchNotFound

        raise ResearchNotFound
    query = (
        select(SqlObjectRevision)
        .join(
            SqlResearchAttemptRevision,
            SqlResearchAttemptRevision.revision_id == SqlObjectRevision.id,
        )
        .where(
            SqlResearchAttemptRevision.target_object_id == target_object_id,
            read_condition(project_id),
        )
    )
    if target_revision_id is not None:
        query = query.where(SqlResearchAttemptRevision.target_revision_id == target_revision_id)
    if cursor:
        anchor_id = decode_cursor(cursor)
        anchor = session.get(SqlObjectRevision, anchor_id)
        anchor_attempt = session.get(SqlResearchAttemptRevision, anchor_id)
        if (
            anchor is None
            or anchor_attempt is None
            or anchor_attempt.target_object_id != target_object_id
            or (
                target_revision_id is not None
                and anchor_attempt.target_revision_id != target_revision_id
            )
        ):
            raise DomainConflict("invalid cursor")
        query = query.where(
            or_(
                SqlObjectRevision.created_at > anchor.created_at,
                and_(
                    SqlObjectRevision.created_at == anchor.created_at,
                    SqlObjectRevision.id > anchor.id,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(SqlObjectRevision.created_at, SqlObjectRevision.id).limit(limit + 1)
        )
    )
    selected = rows[:limit]
    member_rows = [
        row for row in selected if project_id is not None and row.project_id == project_id
    ]
    public_rows = [row for row in selected if project_id is None or row.project_id != project_id]
    projected = {
        item.id: item
        for item in (
            version_reads(session, member_rows, project_id=project_id, public=False)
            + version_reads(session, public_rows, public=True)
        )
    }
    return ObjectVersionPage(
        items=[projected[row.id] for row in selected],
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )

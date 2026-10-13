"""Revision-pinned endorsement and correspondence histories."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import and_, exists, false, or_, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement

from polycolab.access.actors import Actor
from polycolab.access.authorization import require_human_actor
from polycolab.catalogue.admission import lock_commons
from polycolab.db.models import (
    SqlCorrespondenceAssessment,
    SqlObjectRevision,
    SqlRecordRevision,
    SqlRevisionEndorsement,
    SqlUser,
)
from polycolab.platform import mutation_keys
from polycolab.projects.service import DomainConflict
from polycolab.research.contracts import (
    AssuranceCurrentRead,
    AssuranceRead,
    CorrespondenceRead,
    CorrespondenceWrite,
    EndorsementRead,
    EndorsementWrite,
)
from polycolab.research.contributions import human_contribution
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import accessible_revision, project_access

AssuranceKind = Literal["endorsement", "correspondence"]
AssuranceCursor = tuple[datetime, AssuranceKind, UUID]


def _normalized_time(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _encode_cursor(created_at: datetime, kind: AssuranceKind, row_id: UUID) -> str:
    payload = ["v1", _normalized_time(created_at).isoformat(), kind, str(row_id)]
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()


def _decode_cursor(value: str) -> AssuranceCursor:
    try:
        payload = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, list)
            or len(payload) != 4
            or payload[0] != "v1"
            or not isinstance(payload[1], str)
            or payload[2] not in {"endorsement", "correspondence"}
            or not isinstance(payload[3], str)
        ):
            raise ValueError
        created_at = datetime.fromisoformat(payload[1])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at.astimezone(UTC), payload[2], UUID(payload[3])
    except TypeError, ValueError, UnicodeError, binascii.Error, json.JSONDecodeError:
        raise DomainConflict("invalid cursor") from None


def _after(
    model: type[SqlRevisionEndorsement] | type[SqlCorrespondenceAssessment],
    cursor: AssuranceCursor | None,
    kind: AssuranceKind,
) -> ColumnElement[bool] | None:
    if cursor is None:
        return None
    created_at, cursor_kind, row_id = cursor
    kind_after = kind == "correspondence" and cursor_kind == "endorsement"
    same_kind_after = kind == cursor_kind
    tie_breaker = true() if kind_after else model.id > row_id if same_kind_after else false()
    return or_(
        model.created_at > created_at,
        and_(model.created_at == created_at, tie_breaker),
    )


def _later_than(
    model: Any,
    later: Any,
) -> ColumnElement[bool]:
    return or_(
        later.created_at > model.created_at,
        and_(later.created_at == model.created_at, later.id > model.id),
    )


def _authorize_mutation(
    session: Session, *, actor: Actor, project_id: UUID | None, revision_id: UUID
) -> SqlObjectRevision:
    require_human_actor(actor, action="assurance mutation")
    assert actor.human_user_id is not None
    if project_id is not None:
        project_access(session, project_id, actor.human_user_id, write=True)
    lock_commons(session)
    return accessible_revision(session, revision_id, project_id)


def _endorsement_read(session: Session, row: SqlRevisionEndorsement) -> EndorsementRead:
    author = session.get(SqlUser, row.created_by_user_id)
    if author is None:
        raise ResearchNotFound
    return EndorsementRead(
        id=row.id,
        revision_id=row.revision_id,
        assessor_id=row.created_by_user_id,
        active=row.active,
        rationale=row.rationale,
        author_display_name=author.display_name,
        created_at=row.created_at,
    )


def _correspondence_read(session: Session, row: SqlCorrespondenceAssessment) -> CorrespondenceRead:
    author = session.get(SqlUser, row.created_by_user_id)
    if author is None:
        raise ResearchNotFound
    return CorrespondenceRead(
        id=row.id,
        revision_id=row.revision_id,
        statement_revision_id=row.statement_revision_id,
        assessor_id=row.created_by_user_id,
        status=row.status,
        rationale=row.rationale,
        author_display_name=author.display_name,
        created_at=row.created_at,
    )


def endorse(
    session: Session, *, actor: Actor, payload: EndorsementWrite, key: str
) -> EndorsementRead:
    require_human_actor(actor, action="assurance mutation")
    assert actor.human_user_id is not None
    actor_key = f"human:{actor.human_user_id}"
    body = payload.model_dump(mode="json")
    try:
        mutation_keys.lock_key(session, actor_key, "assurance.endorse", key)
        revision = _authorize_mutation(
            session,
            actor=actor,
            project_id=payload.project_id,
            revision_id=payload.revision_id,
        )
        existing = mutation_keys.receipt(session, actor_key, "assurance.endorse", key, body)
        if existing is not None:
            row = session.get(SqlRevisionEndorsement, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            session.commit()
            return _endorsement_read(session, row)
        envelope = human_contribution(
            session,
            user_id=actor.human_user_id,
            scope_id=revision.ownership_scope_id,
            operation="assurance.endorse",
        )
        row = SqlRevisionEndorsement(
            revision_id=revision.id,
            active=payload.active,
            rationale=payload.rationale,
            contribution_id=envelope.id,
            created_by_user_id=actor.human_user_id,
        )
        session.add(row)
        session.flush()
        mutation_keys.save(session, actor_key, "assurance.endorse", key, body, [row.id])
        session.commit()
        session.refresh(row)
        return _endorsement_read(session, row)
    except Exception:
        session.rollback()
        raise


def assess_correspondence(
    session: Session, *, actor: Actor, payload: CorrespondenceWrite, key: str
) -> CorrespondenceRead:
    require_human_actor(actor, action="assurance mutation")
    assert actor.human_user_id is not None
    actor_key = f"human:{actor.human_user_id}"
    body = payload.model_dump(mode="json")
    try:
        mutation_keys.lock_key(session, actor_key, "assurance.correspondence", key)
        revision = _authorize_mutation(
            session,
            actor=actor,
            project_id=payload.project_id,
            revision_id=payload.revision_id,
        )
        if session.get(SqlRecordRevision, revision.id) is None:
            raise ResearchNotFound
        target = accessible_revision(session, payload.statement_revision_id, payload.project_id)
        from polycolab.db.models import SqlStatementRevision

        if session.get(SqlStatementRevision, target.id) is None:
            raise ResearchNotFound
        existing = mutation_keys.receipt(session, actor_key, "assurance.correspondence", key, body)
        if existing is not None:
            row = session.get(SqlCorrespondenceAssessment, UUID(existing.resource_ids[0]))
            if row is None:
                raise ResearchNotFound
            session.commit()
            return _correspondence_read(session, row)
        envelope = human_contribution(
            session,
            user_id=actor.human_user_id,
            scope_id=revision.ownership_scope_id,
            operation="assurance.correspondence",
        )
        row = SqlCorrespondenceAssessment(
            revision_id=revision.id,
            statement_revision_id=payload.statement_revision_id,
            status=payload.status,
            rationale=payload.rationale,
            contribution_id=envelope.id,
            created_by_user_id=actor.human_user_id,
        )
        session.add(row)
        session.flush()
        mutation_keys.save(session, actor_key, "assurance.correspondence", key, body, [row.id])
        session.commit()
        session.refresh(row)
        return _correspondence_read(session, row)
    except Exception:
        session.rollback()
        raise


def _page(
    session: Session,
    *,
    revision_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
    current_only: bool,
) -> AssuranceRead | AssuranceCurrentRead:
    accessible_revision(session, revision_id, project_id)
    anchor = _decode_cursor(cursor) if cursor else None
    endorsement_query = select(SqlRevisionEndorsement).where(
        SqlRevisionEndorsement.revision_id == revision_id
    )
    correspondence_query = select(SqlCorrespondenceAssessment).where(
        SqlCorrespondenceAssessment.revision_id == revision_id
    )
    if current_only:
        later_endorsement = aliased(SqlRevisionEndorsement)
        endorsement_query = endorsement_query.where(
            ~exists(
                select(later_endorsement.id).where(
                    later_endorsement.revision_id == SqlRevisionEndorsement.revision_id,
                    later_endorsement.created_by_user_id
                    == SqlRevisionEndorsement.created_by_user_id,
                    _later_than(SqlRevisionEndorsement, later_endorsement),
                )
            )
        )
        later_correspondence = aliased(SqlCorrespondenceAssessment)
        correspondence_query = correspondence_query.where(
            ~exists(
                select(later_correspondence.id).where(
                    later_correspondence.revision_id == SqlCorrespondenceAssessment.revision_id,
                    later_correspondence.statement_revision_id
                    == SqlCorrespondenceAssessment.statement_revision_id,
                    later_correspondence.created_by_user_id
                    == SqlCorrespondenceAssessment.created_by_user_id,
                    _later_than(SqlCorrespondenceAssessment, later_correspondence),
                )
            )
        )
    endorsement_after = _after(SqlRevisionEndorsement, anchor, "endorsement")
    correspondence_after = _after(SqlCorrespondenceAssessment, anchor, "correspondence")
    if endorsement_after is not None:
        endorsement_query = endorsement_query.where(endorsement_after)
    if correspondence_after is not None:
        correspondence_query = correspondence_query.where(correspondence_after)
    endorsements = list(
        session.scalars(
            endorsement_query.order_by(
                SqlRevisionEndorsement.created_at, SqlRevisionEndorsement.id
            ).limit(limit + 1)
        )
    )
    correspondence_rows = list(
        session.scalars(
            correspondence_query.order_by(
                SqlCorrespondenceAssessment.created_at, SqlCorrespondenceAssessment.id
            ).limit(limit + 1)
        )
    )
    ordered: list[
        tuple[
            datetime, int, UUID, AssuranceKind, SqlRevisionEndorsement | SqlCorrespondenceAssessment
        ]
    ] = [
        (_normalized_time(row.created_at), 0, row.id, "endorsement", row) for row in endorsements
    ] + [
        (_normalized_time(row.created_at), 1, row.id, "correspondence", row)
        for row in correspondence_rows
    ]
    ordered.sort(key=lambda item: item[:3])
    page = ordered[:limit]
    next_cursor = (
        _encode_cursor(page[-1][0], page[-1][3], page[-1][2]) if len(ordered) > limit else None
    )
    endorsement_rows = [
        cast(SqlRevisionEndorsement, row) for _, _, _, kind, row in page if kind == "endorsement"
    ]
    page_correspondence = [
        cast(SqlCorrespondenceAssessment, row)
        for _, _, _, kind, row in page
        if kind == "correspondence"
    ]
    # A once-public target can later become unavailable through moderation.
    # Omit the whole assessment instead of leaking its exact private target.
    visible_correspondence: list[CorrespondenceRead] = []
    for row in page_correspondence:
        try:
            accessible_revision(session, row.statement_revision_id, project_id)
        except ResearchNotFound:
            continue
        visible_correspondence.append(_correspondence_read(session, row))
    response_type = AssuranceCurrentRead if current_only else AssuranceRead
    return response_type(
        revision_id=revision_id,
        endorsements=[_endorsement_read(session, row) for row in endorsement_rows],
        correspondence=visible_correspondence,
        next_cursor=next_cursor,
    )


def history(
    session: Session,
    *,
    revision_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> AssuranceRead:
    result = _page(
        session,
        revision_id=revision_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        current_only=False,
    )
    assert isinstance(result, AssuranceRead)
    return result


def current(
    session: Session,
    *,
    revision_id: UUID,
    project_id: UUID | None,
    limit: int,
    cursor: str | None,
) -> AssuranceCurrentRead:
    result = _page(
        session,
        revision_id=revision_id,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
        current_only=True,
    )
    assert isinstance(result, AssuranceCurrentRead)
    return result

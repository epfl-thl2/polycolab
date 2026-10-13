"""Bounded transactional fan-out; current access is checked on delivery and read."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import exists, or_, select, union
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Subquery

from polycolab.catalogue.admission import lock_commons
from polycolab.catalogue.projections import require_catalogue_entry
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlCatalogueFollow,
    SqlCatalogueRevision,
    SqlCommunityDeliveryCursor,
    SqlMembership,
    SqlObjectRevision,
    SqlOutboxEvent,
    SqlProject,
    SqlProjectReference,
    SqlPublicRelease,
    SqlPublicResearchAnchor,
    SqlResearchNotification,
    SqlResearchObject,
    SqlResearchProgressSummary,
)
from polycolab.entities.time import utc_now
from polycolab.platform.outbox import canonical_digest
from polycolab.research import records
from polycolab.research.objects import ResearchNotFound


def recipients(entry_id: UUID, object_id: UUID) -> Subquery:
    follows = select(SqlCatalogueFollow.user_id).where(
        SqlCatalogueFollow.entry_id == entry_id, SqlCatalogueFollow.active.is_(True)
    )
    references = (
        select(SqlMembership.user_id)
        .join(SqlProjectReference, SqlProjectReference.project_id == SqlMembership.project_id)
        .join(SqlProject, SqlProject.id == SqlMembership.project_id)
        .where(
            SqlProjectReference.object_id.in_([entry_id, object_id]),
            SqlProject.deleted_at.is_(None),
            SqlProject.archived_at.is_(None),
        )
    )
    return union(follows, references).subquery()


def refresh_summary(session: Session, entry_id: UUID) -> None:
    values = list(
        session.scalars(
            select(SqlObjectRevision.id)
            .join(SqlResearchObject, SqlResearchObject.current_revision_id == SqlObjectRevision.id)
            .where(
                records.public_condition(SqlObjectRevision.id),
                exists(
                    select(SqlPublicResearchAnchor.entry_id).where(
                        SqlPublicResearchAnchor.revision_id == SqlObjectRevision.id,
                        SqlPublicResearchAnchor.entry_id == entry_id,
                    )
                ),
            )
            .order_by(SqlObjectRevision.created_at.desc(), SqlObjectRevision.id.desc())
            .limit(50)
        )
    )
    ids = [str(value) for value in values]
    summary = session.get(SqlResearchProgressSummary, entry_id)
    if summary is None:
        session.add(
            SqlResearchProgressSummary(
                entry_id=entry_id, revision_ids=ids, inputs_digest=canonical_digest(ids)
            )
        )
    else:
        summary.revision_ids = ids
        summary.inputs_digest = canonical_digest(ids)
        summary.updated_at = utc_now()


def process_one(session: Session, *, recipient_limit: int = 100) -> bool:
    """One short DB transaction; a durable cursor continues arbitrarily large fan-out."""
    if not 1 <= recipient_limit <= 100:
        raise ValueError("invalid recipient bound")
    try:
        event = session.scalar(
            select(SqlOutboxEvent)
            .where(
                ~exists(
                    select(SqlCommunityDeliveryCursor.event_id).where(
                        SqlCommunityDeliveryCursor.event_id == SqlOutboxEvent.id,
                        SqlCommunityDeliveryCursor.done.is_(True),
                    )
                )
            )
            .order_by(SqlOutboxEvent.created_at, SqlOutboxEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            session.rollback()
            return False
        cursor = session.get(SqlCommunityDeliveryCursor, event.id)
        if cursor is None:
            cursor = SqlCommunityDeliveryCursor(event_id=event.id)
            session.add(cursor)
        revision_id: UUID | None = None
        if event.event_type == "research.created" and event.aggregate_type == "OBJECT_REVISION":
            revision_id = event.aggregate_id
        elif event.event_type.startswith("catalogue.") or event.event_type == "record.moderated":
            raw = event.payload.get("revision_id")
            try:
                revision_id = UUID(str(raw))
            except ValueError:
                pass
        if (
            revision_id is None
            or session.scalar(
                select(SqlPublicRelease.id).where(
                    SqlPublicRelease.object_revision_id == revision_id
                )
            )
            is None
        ):
            cursor.done = True
            session.commit()
            return True
        lock_commons(session)
        entries = select(SqlCatalogueEntry.id).where(
            SqlCatalogueEntry.hidden.is_(False),
            or_(
                SqlCatalogueEntry.id.in_(
                    select(SqlCatalogueRevision.entry_id).where(
                        SqlCatalogueRevision.revision_id == revision_id
                    )
                ),
                SqlCatalogueEntry.id.in_(
                    select(SqlPublicResearchAnchor.entry_id).where(
                        SqlPublicResearchAnchor.revision_id == revision_id
                    )
                ),
            ),
        )
        if cursor.entry_id is not None:
            entries = entries.where(
                SqlCatalogueEntry.id >= cursor.entry_id
                if cursor.user_id is not None
                else SqlCatalogueEntry.id > cursor.entry_id
            )
        entry_id = session.scalar(entries.order_by(SqlCatalogueEntry.id).limit(1))
        if entry_id is None:
            cursor.done = True
        else:
            if entry_id != cursor.entry_id:
                cursor.user_id = None
            if cursor.user_id is None:
                refresh_summary(session, entry_id)
            revision = session.get(SqlObjectRevision, revision_id)
            assert revision is not None
            eligible = recipients(entry_id, revision.object_id)
            users_query = select(eligible.c.user_id)
            if cursor.user_id is not None:
                users_query = users_query.where(eligible.c.user_id > cursor.user_id)
            users = list(
                session.scalars(users_query.order_by(eligible.c.user_id).limit(recipient_limit + 1))
            )
            try:
                records.public_revision(session, revision_id)
                visible = True
            except ResearchNotFound:
                visible = False
            if visible:
                for user_id in users[:recipient_limit]:
                    already = session.scalar(
                        select(SqlResearchNotification.id).where(
                            SqlResearchNotification.user_id == user_id,
                            SqlResearchNotification.event_id == event.id,
                            SqlResearchNotification.entry_id == entry_id,
                        )
                    )
                    if already is None:
                        session.add(
                            SqlResearchNotification(
                                user_id=user_id,
                                event_id=event.id,
                                entry_id=entry_id,
                                revision_id=revision_id,
                            )
                        )
            cursor.entry_id = entry_id
            cursor.user_id = users[recipient_limit - 1] if len(users) > recipient_limit else None
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise


def read_notifications(
    session: Session, *, user_id: UUID, limit: int, cursor: str | None
) -> dict[str, object]:
    # Eligibility is correlated in SQL so revoked references do not occupy pages.
    followed = exists(
        select(SqlCatalogueFollow.user_id).where(
            SqlCatalogueFollow.user_id == user_id,
            SqlCatalogueFollow.entry_id == SqlResearchNotification.entry_id,
            SqlCatalogueFollow.active.is_(True),
        )
    )
    referenced = exists(
        select(SqlProjectReference.id)
        .join(SqlMembership, SqlMembership.project_id == SqlProjectReference.project_id)
        .join(SqlProject, SqlProject.id == SqlProjectReference.project_id)
        .where(
            or_(
                SqlProjectReference.object_id == SqlResearchNotification.entry_id,
                SqlProjectReference.object_id
                == select(SqlObjectRevision.object_id)
                .where(SqlObjectRevision.id == SqlResearchNotification.revision_id)
                .correlate(SqlResearchNotification)
                .scalar_subquery(),
            ),
            SqlMembership.user_id == user_id,
            SqlProject.deleted_at.is_(None),
            SqlProject.archived_at.is_(None),
        )
    )
    query = select(SqlResearchNotification).where(
        SqlResearchNotification.user_id == user_id,
        exists(
            select(SqlCatalogueEntry.id).where(
                SqlCatalogueEntry.id == SqlResearchNotification.entry_id,
                SqlCatalogueEntry.hidden.is_(False),
            )
        ),
        records.public_condition(SqlResearchNotification.revision_id),
        or_(followed, referenced),
    )
    if cursor:
        query = query.where(SqlResearchNotification.id > records.decode_cursor(cursor))
    values = list(session.scalars(query.order_by(SqlResearchNotification.id).limit(limit + 1)))
    return {
        "items": [
            {
                "id": str(value.id),
                "entry_id": str(value.entry_id),
                "object_version_id": str(value.revision_id),
                "created_at": value.created_at.replace(tzinfo=UTC).isoformat(),
            }
            for value in values[:limit]
        ],
        "next_cursor": records.encode_cursor(values[limit - 1].id) if len(values) > limit else None,
    }


def read_summary(session: Session, entry_id: UUID) -> dict[str, object]:
    require_catalogue_entry(session, entry_id)
    summary = session.get(SqlResearchProgressSummary, entry_id)
    if summary is None or summary.inputs_digest != canonical_digest(summary.revision_ids):
        return {
            "entry_id": str(entry_id),
            "state": "PENDING",
            "inputs_digest": None,
            "items": [],
            "status_counts": {},
        }
    ids = [UUID(value) for value in summary.revision_ids[:50]]
    values = list(
        session.scalars(
            select(SqlObjectRevision)
            .where(SqlObjectRevision.id.in_(ids), records.public_condition(SqlObjectRevision.id))
            .order_by(SqlObjectRevision.created_at.desc(), SqlObjectRevision.id.desc())
        )
    )
    items = []
    counts: dict[str, int] = {}
    for value in records.public_record_reads(session, values):
        status = value.reported_outcome
        counts[status or "UNASSESSED"] = counts.get(status or "UNASSESSED", 0) + 1
        items.append(
            {
                "object_version_id": str(value.revision_id),
                "title": value.title,
                "excerpt": value.content_md[:300],
                "reported_outcome": status,
            }
        )
    return {
        "entry_id": str(entry_id),
        "state": "READY",
        "inputs_digest": canonical_digest([str(value.id) for value in values]),
        "items": items,
        "status_counts": counts,
    }

"""Explicit release-only public catalogue projections, never workspace DTOs."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from polycolab.catalogue.read_schemas import PublicCataloguePage, PublicCatalogueRead
from polycolab.catalogue.schemas import CatalogueSource, PublicStatementRead
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlCatalogueRevision,
    SqlObjectRevision,
    SqlPublicRelease,
    SqlRecordModeration,
    SqlResearchObject,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.research.objects import ResearchNotFound
from polycolab.research.version_projections import version_reads
from polycolab.research.version_schemas import ObjectVersionRead


def require_catalogue_entry(
    session: Session, entry_id: UUID, revision_id: UUID | None = None
) -> tuple[SqlCatalogueEntry, SqlCatalogueRevision, SqlObjectRevision]:
    """Authorize a released catalogue version without materializing its graph."""
    row = session.execute(
        select(SqlCatalogueEntry, SqlCatalogueRevision, SqlPublicRelease)
        .join(
            SqlCatalogueRevision,
            and_(
                SqlCatalogueRevision.entry_id == SqlCatalogueEntry.id,
                SqlCatalogueRevision.revision_id
                == (revision_id if revision_id else SqlCatalogueEntry.official_revision_id),
            ),
        )
        .join(
            SqlPublicRelease,
            SqlPublicRelease.object_revision_id == SqlCatalogueRevision.revision_id,
        )
        .where(SqlCatalogueEntry.id == entry_id, SqlCatalogueEntry.hidden.is_(False))
    ).one_or_none()
    if row is None:
        raise ResearchNotFound
    entry, formulation, release = row
    moderation = session.get(SqlRecordModeration, entry.id)
    if moderation is not None and moderation.hidden:
        raise ResearchNotFound
    if release.projection_version not in {1, 2, 4}:
        raise ResearchNotFound
    statement = PublicStatementRead.model_validate(release.public_fields)
    if statement.object_id != entry.id or statement.revision_id != formulation.revision_id:
        raise ResearchNotFound
    revision = session.get(SqlObjectRevision, formulation.revision_id)
    assert revision is not None
    return entry, formulation, revision


def catalogue_entry(
    session: Session, entry_id: UUID, revision_id: UUID | None = None
) -> PublicCatalogueRead:
    entry, formulation, revision = require_catalogue_entry(session, entry_id, revision_id)
    reviewer = (
        session.get(SqlUser, formulation.reviewed_by_user_id)
        if formulation.reviewed_by_user_id
        else None
    )
    return _catalogue_read(
        entry, formulation, version_reads(session, [revision], public=True)[0], reviewer
    )


def _catalogue_read(
    entry: SqlCatalogueEntry,
    formulation: SqlCatalogueRevision,
    version: ObjectVersionRead,
    reviewer: SqlUser | None,
) -> PublicCatalogueRead:
    return PublicCatalogueRead(
        entry_id=entry.id,
        object_version=version,
        source=CatalogueSource(
            identifier=formulation.source_identifier,
            version=formulation.source_version,
            locator=formulation.source_locator,
        )
        if formulation.source_identifier
        and formulation.source_version
        and formulation.source_locator
        else None,
        reported_status=formulation.reported_status,
        admitted_at=entry.created_at,
        review_rationale=formulation.review_rationale,
        reviewer_display_name=(reviewer.display_name or "Researcher") if reviewer else None,
        reviewed_at=formulation.reviewed_at,
    )


def _catalogue_items(
    session: Session, selections: list[tuple[UUID, UUID | None]]
) -> list[PublicCatalogueRead]:
    """Batch a bounded page, retaining exact selection order and public checks."""
    if not selections:
        return []
    rows = session.execute(
        select(
            SqlCatalogueEntry, SqlCatalogueRevision, SqlObjectRevision, SqlPublicRelease, SqlUser
        )
        .join(SqlCatalogueRevision, SqlCatalogueRevision.entry_id == SqlCatalogueEntry.id)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlCatalogueRevision.revision_id)
        .join(SqlPublicRelease, SqlPublicRelease.object_revision_id == SqlObjectRevision.id)
        .outerjoin(SqlUser, SqlUser.id == SqlCatalogueRevision.reviewed_by_user_id)
        .outerjoin(SqlRecordModeration, SqlRecordModeration.object_id == SqlCatalogueEntry.id)
        .where(
            SqlCatalogueEntry.hidden.is_(False),
            SqlPublicRelease.projection_version.in_([1, 2, 4]),
            or_(SqlRecordModeration.object_id.is_(None), SqlRecordModeration.hidden.is_(False)),
            or_(
                *(
                    and_(
                        SqlCatalogueEntry.id == entry_id,
                        SqlCatalogueRevision.revision_id
                        == (version_id if version_id else SqlCatalogueEntry.official_revision_id),
                    )
                    for entry_id, version_id in selections
                )
            ),
        )
    ).all()
    valid = []
    for entry, formulation, revision, release, reviewer in rows:
        statement = PublicStatementRead.model_validate(release.public_fields)
        if statement.object_id == entry.id and statement.revision_id == revision.id:
            valid.append((entry, formulation, revision, reviewer))
    if not valid:
        return []
    try:
        versions = version_reads(session, [row[2] for row in valid], public=True)
    except ResearchNotFound:
        # Reauthorization can observe a concurrent hide. Keep the established
        # per-item omission behavior without penalizing the ordinary read path.
        items = []
        for entry_id, version_id in selections:
            try:
                items.append(catalogue_entry(session, entry_id, version_id))
            except ResearchNotFound:
                continue
        return items
    projected = {
        (entry.id, revision.id): _catalogue_read(entry, formulation, version, reviewer)
        for (entry, formulation, revision, reviewer), version in zip(valid, versions, strict=True)
    }
    official = {entry.id: entry.official_revision_id for entry, _, _, _ in valid}
    return [
        projected[key]
        for entry_id, version_id in selections
        if (key := (entry_id, version_id or official.get(entry_id))) in projected
    ]


def library_page(
    session: Session,
    *,
    query: str = "",
    kind: str | None = None,
    status: str | None = None,
    basis: str | None = None,
    source: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
    entry_id: UUID | None = None,
) -> PublicCataloguePage:
    """Filter admitted, released, visible statements before the page boundary."""
    selection = (
        select(SqlCatalogueRevision.entry_id, SqlObjectRevision.id, SqlObjectRevision.created_at)
        .join(SqlObjectRevision, SqlObjectRevision.id == SqlCatalogueRevision.revision_id)
        .join(SqlCatalogueEntry, SqlCatalogueEntry.id == SqlCatalogueRevision.entry_id)
        .join(SqlResearchObject, SqlResearchObject.id == SqlCatalogueEntry.id)
        .join(SqlStatementRevision, SqlStatementRevision.revision_id == SqlObjectRevision.id)
        .join(SqlPublicRelease, SqlPublicRelease.object_revision_id == SqlObjectRevision.id)
        .outerjoin(SqlRecordModeration, SqlRecordModeration.object_id == SqlCatalogueEntry.id)
        .where(
            SqlCatalogueEntry.hidden.is_(False),
            SqlPublicRelease.projection_version.in_([1, 2, 4]),
            or_(SqlRecordModeration.object_id.is_(None), SqlRecordModeration.hidden.is_(False)),
        )
    )
    if entry_id:
        selection = selection.where(SqlCatalogueEntry.id == entry_id)
    else:
        selection = selection.where(SqlCatalogueEntry.official_revision_id == SqlObjectRevision.id)
    sources = (
        func.coalesce(SqlCatalogueRevision.source_identifier, "")
        + " "
        + func.coalesce(SqlCatalogueRevision.source_version, "")
        + " "
        + func.coalesce(SqlCatalogueRevision.source_locator, "")
    )
    if query.strip():
        selection = selection.where(
            (
                SqlObjectRevision.title
                + " "
                + SqlObjectRevision.content_md
                + " "
                + SqlStatementRevision.assumptions_md
                + " "
                + sources
            ).icontains(query.strip(), autoescape=True)
        )
    if source:
        selection = selection.where(sources.icontains(source, autoescape=True))
    if kind:
        selection = selection.where(SqlResearchObject.kind == kind)
    if status:
        selection = selection.where(SqlCatalogueRevision.reported_status == status)
    if basis == "literature":
        selection = selection.where(SqlCatalogueRevision.source_identifier.is_not(None))
    elif basis == "review":
        selection = selection.where(SqlCatalogueRevision.review_rationale.is_not(None))
    if cursor:
        try:
            version, raw_id, raw_time = (
                base64.b64decode(cursor, altchars=b"-_", validate=True)
                .decode("ascii")
                .split("|", 2)
            )
            if version != "library-v1":
                raise ValueError
            after_id = UUID(raw_id)
            after_time = datetime.fromisoformat(raw_time)
            if after_time.tzinfo is None:
                raise ValueError
        except ValueError, UnicodeError, binascii.Error:
            raise ValueError("invalid Library cursor") from None
        selection = selection.where(
            or_(
                SqlObjectRevision.created_at < after_time,
                and_(SqlObjectRevision.created_at == after_time, SqlObjectRevision.id < after_id),
            )
        )
    rows = list(
        session.execute(
            selection.order_by(
                SqlObjectRevision.created_at.desc(), SqlObjectRevision.id.desc()
            ).limit(limit + 1)
        )
    )
    items = _catalogue_items(session, [(entry, revision) for entry, revision, _ in rows[:limit]])
    next_cursor = None
    if len(rows) > limit:
        _, last_id, last_time = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(
            f"library-v1|{last_id}|{last_time.replace(tzinfo=UTC).isoformat()}".encode()
        ).decode()
    return PublicCataloguePage(items=items, next_cursor=next_cursor)


def catalogue_page(session: Session, *, limit: int, cursor: str | None) -> PublicCataloguePage:
    if not 1 <= limit <= 100:
        raise ValueError("invalid limit")
    query = select(SqlCatalogueEntry.id).where(SqlCatalogueEntry.hidden.is_(False))
    if cursor is not None:
        try:
            decoded = base64.b64decode(cursor, altchars=b"-_", validate=True).decode("ascii")
            version, value = decoded.split(":", 1)
            if version != "v1":
                raise ValueError
            after = UUID(value)
        except ValueError, UnicodeError, binascii.Error:
            raise ValueError("invalid catalogue cursor") from None
        query = query.where(SqlCatalogueEntry.id > after)
    ids = list(session.scalars(query.order_by(SqlCatalogueEntry.id).limit(limit + 1)))
    next_cursor = None
    if len(ids) > limit:
        next_cursor = base64.urlsafe_b64encode(f"v1:{ids[limit - 1]}".encode()).decode()
    items = _catalogue_items(session, [(entry_id, None) for entry_id in ids[:limit]])
    return PublicCataloguePage(items=items, next_cursor=next_cursor)

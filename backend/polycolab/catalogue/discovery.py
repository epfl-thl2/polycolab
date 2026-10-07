"""Bounded canonical discovery; authorization precedes every page boundary."""

from uuid import UUID

from sqlalchemy import exists, func, literal_column, or_, select, union
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from polycolab.db.models import (
    SqlCatalogueRevision,
    SqlObjectRevision,
    SqlRecordRevision,
    SqlResearchAttachment,
    SqlResearchObject,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.entities.object_kinds import ObjectKind
from polycolab.research import records
from polycolab.research.contracts import DiscoveryHit, DiscoveryPage


def search(
    session: Session,
    *,
    project_id: UUID | None,
    public_only: bool = False,
    query: str = "",
    kind: ObjectKind | None = None,
    statement_id: UUID | None = None,
    author: str | None = None,
    status: str | None = None,
    source: str | None = None,
    limit: int = 25,
    cursor: str | None = None,
) -> DiscoveryPage:
    selection = (
        select(SqlObjectRevision, SqlCatalogueRevision)
        .join(SqlResearchObject, SqlResearchObject.id == SqlObjectRevision.object_id)
        .outerjoin(SqlCatalogueRevision, SqlCatalogueRevision.revision_id == SqlObjectRevision.id)
        .outerjoin(SqlRecordRevision, SqlRecordRevision.revision_id == SqlObjectRevision.id)
        .outerjoin(SqlStatementRevision, SqlStatementRevision.revision_id == SqlObjectRevision.id)
        .join(SqlUser, SqlUser.id == SqlObjectRevision.created_by_user_id)
        .where(SqlResearchObject.current_revision_id == SqlObjectRevision.id)
        .where(
            records.public_condition(SqlObjectRevision.id)
            if project_id is None or public_only
            else SqlObjectRevision.project_id == project_id
        )
    )
    if project_id is not None:
        selection = selection.where(SqlObjectRevision.project_id == project_id)
    if query.strip():
        content_match: ColumnElement[bool]
        source_match: ColumnElement[bool]
        if session.get_bind().dialect.name == "postgresql":
            text_query = func.plainto_tsquery(literal_column("'simple'"), query)
            content_match = func.to_tsvector(
                literal_column("'simple'"),
                SqlObjectRevision.title + " " + SqlObjectRevision.content_md,
            ).op("@@")(text_query)
            explanation_match = func.to_tsvector(
                literal_column("'simple'"), func.coalesce(SqlRecordRevision.explanation_md, "")
            ).op("@@")(text_query)
            source_match = func.to_tsvector(
                literal_column("'simple'"),
                SqlCatalogueRevision.source_identifier
                + " "
                + SqlCatalogueRevision.source_version
                + " "
                + SqlCatalogueRevision.source_locator,
            ).op("@@")(text_query)
            selection = selection.where(
                SqlObjectRevision.id.in_(
                    union(
                        select(SqlObjectRevision.id).where(content_match),
                        select(SqlCatalogueRevision.revision_id).where(source_match),
                        select(SqlRecordRevision.revision_id).where(explanation_match),
                    )
                )
            )
        else:
            content_match = (
                SqlObjectRevision.title + " " + SqlObjectRevision.content_md
            ).icontains(query, autoescape=True)
            source_match = (
                SqlCatalogueRevision.source_identifier
                + " "
                + SqlCatalogueRevision.source_version
                + " "
                + SqlCatalogueRevision.source_locator
            ).icontains(query, autoescape=True)
            selection = selection.where(
                or_(
                    content_match,
                    source_match,
                    SqlRecordRevision.explanation_md.icontains(query, autoescape=True),
                )
            )
    if kind is not None:
        selection = selection.where(SqlResearchObject.canonical_kind == kind)
    if statement_id is not None:
        selection = selection.where(
            or_(
                SqlObjectRevision.id == statement_id,
                exists(
                    select(SqlResearchAttachment.revision_id).where(
                        SqlResearchAttachment.revision_id == SqlObjectRevision.id,
                        SqlResearchAttachment.statement_revision_id == statement_id,
                    )
                ),
            )
        )
    if author is not None:
        selection = selection.where(SqlUser.display_name.icontains(author, autoescape=True))
    if status is not None:
        selection = selection.where(
            or_(
                SqlRecordRevision.reported_outcome == status,
                SqlStatementRevision.reported_outcome == status,
                SqlCatalogueRevision.reported_status == status,
            )
        )
    if source is not None:
        selection = selection.where(
            (
                SqlCatalogueRevision.source_identifier
                + " "
                + SqlCatalogueRevision.source_version
                + " "
                + SqlCatalogueRevision.source_locator
            ).icontains(source, autoescape=True)
        )
    if cursor is not None:
        selection = selection.where(SqlObjectRevision.id > records.decode_cursor(cursor))
    rows = list(session.execute(selection.order_by(SqlObjectRevision.id).limit(limit + 1)))
    return DiscoveryPage(
        items=[
            DiscoveryHit(
                record=(
                    records.public_record_read(session, revision)
                    if public_only
                    else records.record_read(session, revision, project_id)
                ),
                catalogue_entry_id=metadata.entry_id if metadata else None,
                source_identifier=metadata.source_identifier if metadata else None,
                source_version=metadata.source_version if metadata else None,
                source_locator=metadata.source_locator if metadata else None,
                catalogue_status=metadata.reported_status if metadata else None,
            )
            for revision, metadata in rows[:limit]
        ],
        next_cursor=records.encode_cursor(rows[limit - 1][0].id) if len(rows) > limit else None,
    )

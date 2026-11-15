"""SQL operations and retry receipts for the agent library."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from polycolab.db.converters.library import content_entity, item_entity, version_entity
from polycolab.db.errors import persistence_boundary
from polycolab.db.models.library import (
    SqlLibraryDraft,
    SqlLibraryItem,
    SqlLibraryModeration,
    SqlLibraryVersion,
)
from polycolab.entities.library import (
    LibraryContent,
    LibraryItem,
    LibraryKind,
    LibraryOwned,
    LibraryVersion,
)
from polycolab.platform import idempotency


class SqlLibraryStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    @persistence_boundary
    def item(self, item_id: UUID, *, lock: bool = False) -> LibraryItem | None:
        query = select(SqlLibraryItem).where(SqlLibraryItem.id == item_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.session.scalar(query)
        return item_entity(row) if row else None

    @persistence_boundary
    def draft(self, item_id: UUID) -> LibraryContent:
        row = self.session.get(SqlLibraryDraft, item_id)
        assert row is not None
        return content_entity(row.content)

    @persistence_boundary
    def version(self, version_id: UUID) -> LibraryVersion | None:
        row = self.session.get(SqlLibraryVersion, version_id)
        return version_entity(row) if row else None

    def _filters(
        self,
        kind: LibraryKind | None,
        q: str,
        tag: str,
        column: InstrumentedAttribute[dict[str, object]],
    ) -> list[ColumnElement[bool]]:
        # JSON content is searched without loading private drafts into public projections.
        conditions: list[ColumnElement[bool]] = []
        if kind:
            conditions.append(SqlLibraryItem.kind == kind)
        if self.session.get_bind().dialect.name == "postgresql":
            tags = (
                func.json_array_elements_text(column["tags"]).table_valued("value").render_derived()
            )
        else:
            tags = func.json_each(column, "$.tags").table_valued("key", "value")
        if q:
            data = column  # concrete JSON SQL column supplied by the listing
            conditions.append(
                func.lower(data["title"].as_string()).contains(q.lower(), autoescape=True)
                | func.lower(data["description"].as_string()).contains(q.lower(), autoescape=True)
                | exists(
                    select(1)
                    .select_from(tags)
                    .where(func.lower(tags.c.value).contains(q.lower(), autoescape=True))
                )
            )
        if tag:
            conditions.append(exists(select(1).select_from(tags).where(tags.c.value == tag)))
        return conditions

    @persistence_boundary
    def public_items(
        self, *, kind: LibraryKind | None, q: str, tag: str, after: UUID | None, limit: int
    ) -> list[LibraryItem]:
        query = (
            select(SqlLibraryItem)
            .join(
                SqlLibraryVersion,
                SqlLibraryItem.published_version_id == SqlLibraryVersion.id,
            )
            .where(
                ~SqlLibraryItem.hidden,
                ~SqlLibraryItem.archived,
                *self._filters(kind, q, tag, SqlLibraryVersion.content),
            )
        )
        if after:
            query = query.where(SqlLibraryItem.id < after)
        return [
            item_entity(row)
            for row in self.session.scalars(query.order_by(SqlLibraryItem.id.desc()).limit(limit))
        ]

    @persistence_boundary
    def owned_items(
        self,
        owner_id: UUID,
        *,
        kind: LibraryKind | None,
        q: str,
        tag: str,
        after: UUID | None,
        limit: int,
    ) -> list[LibraryOwned]:
        query = (
            select(SqlLibraryItem, SqlLibraryDraft)
            .join(SqlLibraryDraft, SqlLibraryDraft.item_id == SqlLibraryItem.id)
            .where(
                SqlLibraryItem.owner_user_id == owner_id,
                *self._filters(kind, q, tag, SqlLibraryDraft.content),
            )
        )
        if after:
            query = query.where(SqlLibraryItem.id < after)
        result = []
        for item, draft in self.session.execute(
            query.order_by(SqlLibraryItem.id.desc()).limit(limit)
        ):
            source = self.version(item.source_version_id) if item.source_version_id else None
            result.append(
                LibraryOwned(
                    item_entity(item),
                    content_entity(draft.content),
                    source.item_id if source else None,
                )
            )
        return result

    @persistence_boundary
    def versions(self, item_id: UUID, *, after: UUID | None, limit: int) -> list[LibraryVersion]:
        query = select(SqlLibraryVersion).where(SqlLibraryVersion.item_id == item_id)
        if after:
            query = query.where(SqlLibraryVersion.id < after)
        return [
            version_entity(row)
            for row in self.session.scalars(
                query.order_by(SqlLibraryVersion.id.desc()).limit(limit)
            )
        ]

    @persistence_boundary
    def create(
        self,
        owner_id: UUID,
        kind: LibraryKind,
        content: LibraryContent,
        source_version_id: UUID | None = None,
    ) -> UUID:
        row = SqlLibraryItem(owner_user_id=owner_id, kind=kind, source_version_id=source_version_id)
        self.session.add(row)
        self.session.flush()
        self.session.add(SqlLibraryDraft(item_id=row.id, content=asdict(content)))
        self.session.flush()
        return row.id

    def _row(self, item_id: UUID) -> SqlLibraryItem:
        row = self.session.get(SqlLibraryItem, item_id)
        assert row is not None
        row.revision += 1
        return row

    @persistence_boundary
    def update_draft(self, item_id: UUID, content: LibraryContent) -> None:
        self._row(item_id)
        row = self.session.get(SqlLibraryDraft, item_id)
        assert row is not None
        row.content = asdict(content)
        self.session.flush()

    @persistence_boundary
    def publish(self, item: LibraryItem, content: LibraryContent, author_name: str) -> UUID:
        number = (
            self.session.scalar(
                select(func.max(SqlLibraryVersion.number)).where(
                    SqlLibraryVersion.item_id == item.id
                )
            )
            or 0
        )
        version = SqlLibraryVersion(
            item_id=item.id,
            number=number + 1,
            content=asdict(content),
            author_user_id=item.owner_user_id,
            author_name=author_name,
        )
        self.session.add(version)
        self.session.flush()
        self._row(item.id).published_version_id = version.id
        self.session.flush()
        return version.id

    @persistence_boundary
    def set_archived(self, item_id: UUID, archived: bool) -> None:
        self._row(item_id).archived = archived
        self.session.flush()

    @persistence_boundary
    def moderate(self, item_id: UUID, user_id: UUID, hidden: bool, reason: str) -> None:
        self._row(item_id).hidden = hidden
        self.session.add(
            SqlLibraryModeration(
                item_id=item_id, actor_user_id=user_id, hidden=hidden, reason=reason
            )
        )
        self.session.flush()

    @persistence_boundary
    def retry(self, user_id: UUID, operation: str, key: str, payload: object) -> list[UUID] | None:
        actor = f"human:{user_id}"
        idempotency.lock_key(self.session, actor, operation, key)
        row = idempotency.record(self.session, actor, operation, key, payload)
        return [UUID(value) for value in row.resource_ids] if row else None

    @persistence_boundary
    def remember(
        self, user_id: UUID, operation: str, key: str, payload: object, ids: list[UUID]
    ) -> None:
        idempotency.save(self.session, f"human:{user_id}", operation, key, payload, ids)
        self.session.flush()

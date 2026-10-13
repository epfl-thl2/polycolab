"""SQL operations and retry receipts for the agent library."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.sql.elements import ColumnElement

from polycolab.db.converters.agent_library import content_entity, entry_entity, version_entity
from polycolab.db.errors import persistence_boundary
from polycolab.db.models.agent_library import (
    SqlAgentLibraryDraft,
    SqlAgentLibraryEntry,
    SqlAgentLibraryModeration,
    SqlAgentLibraryVersion,
)
from polycolab.entities.agent_library import (
    LibraryContent,
    LibraryEntry,
    LibraryKind,
    LibraryOwned,
    LibraryVersion,
)
from polycolab.platform import mutation_keys


class SqlAgentLibraryStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    @persistence_boundary
    def entry(self, entry_id: UUID, *, lock: bool = False) -> LibraryEntry | None:
        query = select(SqlAgentLibraryEntry).where(SqlAgentLibraryEntry.id == entry_id)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.session.scalar(query)
        return entry_entity(row) if row else None

    @persistence_boundary
    def draft(self, entry_id: UUID) -> LibraryContent:
        row = self.session.get(SqlAgentLibraryDraft, entry_id)
        assert row is not None
        return content_entity(row.content)

    @persistence_boundary
    def version(self, version_id: UUID) -> LibraryVersion | None:
        row = self.session.get(SqlAgentLibraryVersion, version_id)
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
            conditions.append(SqlAgentLibraryEntry.kind == kind)
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
    def public_entries(
        self, *, kind: LibraryKind | None, q: str, tag: str, after: UUID | None, limit: int
    ) -> list[LibraryEntry]:
        query = (
            select(SqlAgentLibraryEntry)
            .join(
                SqlAgentLibraryVersion,
                SqlAgentLibraryEntry.published_version_id == SqlAgentLibraryVersion.id,
            )
            .where(
                ~SqlAgentLibraryEntry.hidden,
                ~SqlAgentLibraryEntry.archived,
                *self._filters(kind, q, tag, SqlAgentLibraryVersion.content),
            )
        )
        if after:
            query = query.where(SqlAgentLibraryEntry.id < after)
        return [
            entry_entity(row)
            for row in self.session.scalars(
                query.order_by(SqlAgentLibraryEntry.id.desc()).limit(limit)
            )
        ]

    @persistence_boundary
    def owned_entries(
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
            select(SqlAgentLibraryEntry, SqlAgentLibraryDraft)
            .join(SqlAgentLibraryDraft, SqlAgentLibraryDraft.entry_id == SqlAgentLibraryEntry.id)
            .where(
                SqlAgentLibraryEntry.owner_user_id == owner_id,
                *self._filters(kind, q, tag, SqlAgentLibraryDraft.content),
            )
        )
        if after:
            query = query.where(SqlAgentLibraryEntry.id < after)
        result = []
        for entry, draft in self.session.execute(
            query.order_by(SqlAgentLibraryEntry.id.desc()).limit(limit)
        ):
            source = self.version(entry.source_version_id) if entry.source_version_id else None
            result.append(
                LibraryOwned(
                    entry_entity(entry),
                    content_entity(draft.content),
                    source.entry_id if source else None,
                )
            )
        return result

    @persistence_boundary
    def versions(self, entry_id: UUID, *, after: UUID | None, limit: int) -> list[LibraryVersion]:
        query = select(SqlAgentLibraryVersion).where(SqlAgentLibraryVersion.entry_id == entry_id)
        if after:
            query = query.where(SqlAgentLibraryVersion.id < after)
        return [
            version_entity(row)
            for row in self.session.scalars(
                query.order_by(SqlAgentLibraryVersion.id.desc()).limit(limit)
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
        row = SqlAgentLibraryEntry(
            owner_user_id=owner_id, kind=kind, source_version_id=source_version_id
        )
        self.session.add(row)
        self.session.flush()
        self.session.add(SqlAgentLibraryDraft(entry_id=row.id, content=asdict(content)))
        self.session.flush()
        return row.id

    def _row(self, entry_id: UUID) -> SqlAgentLibraryEntry:
        row = self.session.get(SqlAgentLibraryEntry, entry_id)
        assert row is not None
        row.revision += 1
        return row

    @persistence_boundary
    def update_draft(self, entry_id: UUID, content: LibraryContent) -> None:
        self._row(entry_id)
        row = self.session.get(SqlAgentLibraryDraft, entry_id)
        assert row is not None
        row.content = asdict(content)
        self.session.flush()

    @persistence_boundary
    def publish(self, entry: LibraryEntry, content: LibraryContent, author_name: str) -> UUID:
        number = (
            self.session.scalar(
                select(func.max(SqlAgentLibraryVersion.number)).where(
                    SqlAgentLibraryVersion.entry_id == entry.id
                )
            )
            or 0
        )
        version = SqlAgentLibraryVersion(
            entry_id=entry.id,
            number=number + 1,
            content=asdict(content),
            author_user_id=entry.owner_user_id,
            author_name=author_name,
        )
        self.session.add(version)
        self.session.flush()
        self._row(entry.id).published_version_id = version.id
        self.session.flush()
        return version.id

    @persistence_boundary
    def set_archived(self, entry_id: UUID, archived: bool) -> None:
        self._row(entry_id).archived = archived
        self.session.flush()

    @persistence_boundary
    def moderate(self, entry_id: UUID, user_id: UUID, hidden: bool, reason: str) -> None:
        self._row(entry_id).hidden = hidden
        self.session.add(
            SqlAgentLibraryModeration(
                entry_id=entry_id, actor_user_id=user_id, hidden=hidden, reason=reason
            )
        )
        self.session.flush()

    @persistence_boundary
    def retry(self, user_id: UUID, operation: str, key: str, payload: object) -> list[UUID] | None:
        actor = f"human:{user_id}"
        mutation_keys.lock_key(self.session, actor, operation, key)
        row = mutation_keys.receipt(self.session, actor, operation, key, payload)
        return [UUID(value) for value in row.resource_ids] if row else None

    @persistence_boundary
    def remember(
        self, user_id: UUID, operation: str, key: str, payload: object, ids: list[UUID]
    ) -> None:
        mutation_keys.save(self.session, f"human:{user_id}", operation, key, payload, ids)
        self.session.flush()

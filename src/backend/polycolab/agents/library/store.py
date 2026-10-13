"""Persistence interface for agent-library workflows."""

from typing import Protocol
from uuid import UUID

from polycolab.entities.agent_library import (
    LibraryContent,
    LibraryEntry,
    LibraryKind,
    LibraryOwned,
    LibraryVersion,
)


class AgentLibraryStore(Protocol):
    def entry(self, entry_id: UUID, *, lock: bool = False) -> LibraryEntry | None: ...
    def draft(self, entry_id: UUID) -> LibraryContent: ...
    def version(self, version_id: UUID) -> LibraryVersion | None: ...
    def public_entries(
        self, *, kind: LibraryKind | None, q: str, tag: str, after: UUID | None, limit: int
    ) -> list[LibraryEntry]: ...
    def owned_entries(
        self,
        owner_id: UUID,
        *,
        kind: LibraryKind | None,
        q: str,
        tag: str,
        after: UUID | None,
        limit: int,
    ) -> list[LibraryOwned]: ...
    def versions(
        self, entry_id: UUID, *, after: UUID | None, limit: int
    ) -> list[LibraryVersion]: ...
    def create(
        self,
        owner_id: UUID,
        kind: LibraryKind,
        content: LibraryContent,
        source_version_id: UUID | None = None,
    ) -> UUID: ...
    def update_draft(self, entry_id: UUID, content: LibraryContent) -> None: ...
    def publish(self, entry: LibraryEntry, content: LibraryContent, author_name: str) -> UUID: ...
    def set_archived(self, entry_id: UUID, archived: bool) -> None: ...
    def moderate(self, entry_id: UUID, user_id: UUID, hidden: bool, reason: str) -> None: ...
    def retry(
        self, user_id: UUID, operation: str, key: str, payload: object
    ) -> list[UUID] | None: ...
    def remember(
        self, user_id: UUID, operation: str, key: str, payload: object, ids: list[UUID]
    ) -> None: ...

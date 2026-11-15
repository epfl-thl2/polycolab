"""Persistence interface for library workflows."""

from typing import Protocol
from uuid import UUID

from polycolab.entities.library import (
    LibraryContent,
    LibraryItem,
    LibraryKind,
    LibraryOwned,
    LibraryVersion,
)


class LibraryStore(Protocol):
    def item(self, item_id: UUID, *, lock: bool = False) -> LibraryItem | None: ...
    def draft(self, item_id: UUID) -> LibraryContent: ...
    def version(self, version_id: UUID) -> LibraryVersion | None: ...
    def public_items(
        self, *, kind: LibraryKind | None, q: str, tag: str, after: UUID | None, limit: int
    ) -> list[LibraryItem]: ...
    def owned_items(
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
        self, item_id: UUID, *, after: UUID | None, limit: int
    ) -> list[LibraryVersion]: ...
    def create(
        self,
        owner_id: UUID,
        kind: LibraryKind,
        content: LibraryContent,
        source_version_id: UUID | None = None,
    ) -> UUID: ...
    def update_draft(self, item_id: UUID, content: LibraryContent) -> None: ...
    def publish(self, item: LibraryItem, content: LibraryContent, author_name: str) -> UUID: ...
    def set_archived(self, item_id: UUID, archived: bool) -> None: ...
    def moderate(self, item_id: UUID, user_id: UUID, hidden: bool, reason: str) -> None: ...
    def retry(
        self, user_id: UUID, operation: str, key: str, payload: object
    ) -> list[UUID] | None: ...
    def remember(
        self, user_id: UUID, operation: str, key: str, payload: object, ids: list[UUID]
    ) -> None: ...

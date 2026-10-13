"""Materialized agent-library values without transport or database dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

LibraryKind = Literal["PROMPT", "SKILL", "PLUGIN"]


@dataclass(frozen=True, slots=True)
class LibraryContent:
    title: str
    description: str
    content: str = ""
    instructions: str = ""
    tags: tuple[str, ...] = ()
    license: str = ""
    source_url: str = ""
    runtime: str = ""
    source_reference: str = ""


@dataclass(frozen=True, slots=True)
class LibraryEntry:
    id: UUID
    owner_user_id: UUID
    kind: LibraryKind
    revision: int
    published_version_id: UUID | None
    source_version_id: UUID | None
    archived: bool
    hidden: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryVersion:
    id: UUID
    entry_id: UUID
    number: int
    content: LibraryContent
    author_user_id: UUID
    author_name: str
    published_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryOwned:
    entry: LibraryEntry
    draft: LibraryContent
    source_entry_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class LibraryPublic:
    id: UUID
    kind: LibraryKind
    source_version_id: UUID | None
    archived: bool
    version: LibraryVersion
    source_entry_id: UUID | None = None

"""Query-free conversion of agent library rows."""

from datetime import UTC, datetime
from typing import cast

from polycolab.db.models.library import SqlLibraryItem, SqlLibraryVersion
from polycolab.entities.library import (
    LibraryContent,
    LibraryItem,
    LibraryKind,
    LibraryVersion,
)


def content_entity(value: dict[str, object]) -> LibraryContent:
    return LibraryContent(
        title=str(value["title"]),
        description=str(value["description"]),
        content=str(value.get("content", "")),
        instructions=str(value.get("instructions", "")),
        tags=tuple(cast(list[str], value.get("tags", []))),
        license=str(value.get("license", "")),
        source_url=str(value.get("source_url", "")),
        runtime=str(value.get("runtime", "")),
        source_reference=str(value.get("source_reference", "")),
    )


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def item_entity(row: SqlLibraryItem) -> LibraryItem:
    return LibraryItem(
        row.id,
        row.owner_user_id,
        cast(LibraryKind, row.kind),
        row.revision,
        row.published_version_id,
        row.source_version_id,
        row.archived,
        row.hidden,
        aware(row.created_at),
    )


def version_entity(row: SqlLibraryVersion) -> LibraryVersion:
    return LibraryVersion(
        row.id,
        row.item_id,
        row.number,
        content_entity(row.content),
        row.author_user_id,
        row.author_name,
        aware(row.published_at),
    )

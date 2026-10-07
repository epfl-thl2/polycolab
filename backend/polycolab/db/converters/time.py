"""Normalize database timestamps at the application boundary."""

from datetime import UTC, datetime
from typing import overload


@overload
def timestamp(value: datetime) -> datetime: ...


@overload
def timestamp(value: None) -> None: ...


def timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    # SQLite's lightweight tests drop timezone information; persisted timestamps
    # use UTC. PostgreSQL timestamptz values already carry their timezone.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

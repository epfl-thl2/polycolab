"""UTC clock values shared by application operations and persistence defaults."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)

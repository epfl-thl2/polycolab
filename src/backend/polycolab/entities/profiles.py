"""Public researcher projections without account or authentication details."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PublicResearcher:
    user_id: UUID
    username: str | None
    display_name: str
    authored_contributions: int
    sponsored_contributions: int

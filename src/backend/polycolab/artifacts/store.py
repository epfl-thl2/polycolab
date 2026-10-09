"""Persistence operations for artifact cleanup; callers own transactions."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from polycolab.entities.artifacts import StoredArtifact
from polycolab.entities.enums import ArtifactState


class ArtifactStore(Protocol):
    def expired_for_update(
        self,
        *,
        states: tuple[ArtifactState, ...],
        before: datetime,
        limit: int,
        after: UUID | None,
    ) -> list[StoredArtifact]: ...

    def get_for_update(self, artifact_id: UUID) -> StoredArtifact | None: ...

    def set_state(
        self,
        artifact_id: UUID,
        state: ArtifactState,
        *,
        deleted_at: datetime | None = None,
    ) -> None: ...

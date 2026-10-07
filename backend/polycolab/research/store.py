"""Materialized research snapshots; callers authorize the selected identities."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from polycolab.entities.research import (
    ObjectVersionRelationship,
    ProofSketch,
    ResearchAttempt,
    ResearchObjectVersion,
    ResearchRecord,
    ResearchStatement,
)

ResearchObjectSnapshot = ResearchStatement | ResearchRecord | ProofSketch | ResearchAttempt


class ResearchReadStore(Protocol):
    def relationships(
        self, relationship_ids: Sequence[UUID]
    ) -> dict[UUID, ObjectVersionRelationship]:
        """Load attributed canonical relationships, without selecting object heads."""
        ...

    def versions(self, version_ids: Sequence[UUID]) -> dict[UUID, ResearchObjectVersion]:
        """Load complete snapshots in bounded batches, without lazy relationships."""
        ...

    def objects(self, object_ids: Sequence[UUID]) -> dict[UUID, ResearchObjectSnapshot]:
        """Load stable identities without loading version content; never serialize publicly."""
        ...

"""Materialize selected research identities through the application read boundary.

The caller must authorize identities before requesting snapshots. Public release
projection remains separate: raw snapshots must never be serialized anonymously.
"""

from collections.abc import Sequence
from uuid import UUID

from polycolab.entities.research import (
    ObjectVersionRelationship,
    ResearchObjectRead,
    ResearchObjectVersion,
)
from polycolab.research.store import ResearchObjectSnapshot, ResearchReadStore


class ResearchSnapshots:
    def __init__(self, store: ResearchReadStore) -> None:
        self.store = store

    def versions(self, version_ids: Sequence[UUID]) -> tuple[ResearchObjectVersion, ...]:
        snapshots = self.store.versions(version_ids)
        if any(version_id not in snapshots for version_id in version_ids):
            raise LookupError("research version not found")
        return tuple(snapshots[version_id] for version_id in version_ids)

    def relationships(
        self, relationship_ids: Sequence[UUID]
    ) -> tuple[ObjectVersionRelationship, ...]:
        rows = self.store.relationships(relationship_ids)
        if any(relationship_id not in rows for relationship_id in relationship_ids):
            raise LookupError("research relationship not found")
        return tuple(rows[relationship_id] for relationship_id in relationship_ids)

    def objects(self, object_ids: Sequence[UUID]) -> tuple[ResearchObjectSnapshot, ...]:
        objects = self.store.objects(object_ids)
        if any(object_id not in objects for object_id in object_ids):
            raise LookupError("research object not found")
        return tuple(objects[object_id] for object_id in object_ids)

    def selected_objects(self, version_ids: Sequence[UUID]) -> tuple[ResearchObjectRead, ...]:
        """Pair identities with caller-authorized selections without replacing their heads."""
        versions = self.versions(version_ids)
        objects = self.store.objects([version.object_id for version in versions])
        if any(version.object_id not in objects for version in versions):
            raise LookupError("research object not found")
        return tuple(
            ResearchObjectRead(object=objects[version.object_id], version=version)
            for version in versions
        )

"""Materialize stored artifact metadata without exposing ORM state."""

from polycolab.db.converters.time import timestamp
from polycolab.db.models import SqlArtifact
from polycolab.entities.artifacts import ArtifactIntegrity, StoredArtifact


def artifact(row: SqlArtifact) -> StoredArtifact:
    return StoredArtifact(
        row.id,
        ArtifactIntegrity(row.sha256, row.byte_length),
        row.media_type,
        row.state,
        timestamp(row.expires_at),
        row.storage_key,
    )

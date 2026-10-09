"""Artifact application values independent of byte and database adapters."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from polycolab.entities.enums import ArtifactState

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


class ArtifactStorageError(Exception):
    """Only normalized codes may cross the API boundary."""


@dataclass(frozen=True, slots=True)
class ArtifactIntegrity:
    sha256: str
    byte_length: int

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ArtifactStorageError("artifact_invalid_digest")
        if not 0 <= self.byte_length <= MAX_ARTIFACT_BYTES:
            raise ArtifactStorageError("artifact_size_limit")


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    id: UUID
    integrity: ArtifactIntegrity
    media_type: str
    state: ArtifactState
    expires_at: datetime
    storage_key: str = field(repr=False)

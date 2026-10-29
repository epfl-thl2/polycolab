"""Project artifact upload and read contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from polycolab.artifacts.storage import MAX_ARTIFACT_BYTES, ArtifactIntegrity
from polycolab.entities.enums import ArtifactState


class ArtifactUploadDeclaration(BaseModel):
    """Client declarations are validated again against bytes; never provenance.

    Scope, authorship, storage identity and execution provenance are resolved by
    domain authorization, not accepted as arbitrary upload metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)
    byte_length: int = Field(strict=True, ge=0, le=MAX_ARTIFACT_BYTES)
    media_type: str = Field(
        default="application/octet-stream",
        min_length=3,
        max_length=127,
        pattern=r"^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$",
    )

    def integrity(self) -> ArtifactIntegrity:
        return ArtifactIntegrity(self.sha256, self.byte_length)


class ArtifactRead(BaseModel):
    id: UUID
    sha256: str
    byte_length: int
    media_type: str
    state: ArtifactState
    expires_at: datetime


def private_download_headers() -> dict[str, str]:
    """Untrusted content is a generic download; no raw names or storage URLs.

    Use only after current read authorization and byte verification. Stored MIME
    declarations are display metadata, not permission to render active content.
    """
    return {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="artifact.bin"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Referrer-Policy": "no-referrer",
    }

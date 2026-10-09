"""Artifact boundary primitives, pending research-owned public API registration."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from polycolab.artifacts.storage import MAX_ARTIFACT_BYTES, ArtifactIntegrity
from polycolab.entities.enums import ArtifactResearchRole, ArtifactState


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


class ArtifactAttachmentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_version_id: UUID
    attempt_object_version_id: UUID | None = None
    role: ArtifactResearchRole


class ArtifactAttachmentRead(BaseModel):
    id: UUID


class ArtifactAttachmentItem(BaseModel):
    attachment_id: UUID
    artifact: ArtifactRead
    source_object_version_id: UUID | None
    object_version_id: UUID
    attempt_object_version_id: UUID | None
    role: ArtifactResearchRole
    created_at: datetime


class ArtifactAttachmentPage(BaseModel):
    items: list[ArtifactAttachmentItem]
    next_cursor: str | None


class PublishedArtifactLinkRead(BaseModel):
    revision_id: UUID
    attempt_revision_id: UUID | None
    role: ArtifactResearchRole


class PublishedArtifactRead(BaseModel):
    """Frozen publication encoding; do not rename fields in stored manifests."""

    id: UUID
    sha256: str
    byte_length: int
    media_type: str
    source_revision_id: UUID | None
    links: list[PublishedArtifactLinkRead]
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime
    content_path: str


class PublishedArtifactVersionLinkRead(BaseModel):
    object_version_id: UUID
    attempt_object_version_id: UUID | None
    role: ArtifactResearchRole


class PublishedArtifactVersionRead(BaseModel):
    """Live projection of an authorized frozen artifact release."""

    id: UUID
    sha256: str
    byte_length: int
    media_type: str
    source_object_version_id: UUID | None
    links: list[PublishedArtifactVersionLinkRead]
    author_display_name: str | None
    actor_kind: str
    agent_display_name: str | None
    created_at: datetime
    content_path: str

    @classmethod
    def from_release(cls, release: PublishedArtifactRead) -> PublishedArtifactVersionRead:
        value = release.model_dump(exclude={"source_revision_id", "links"})
        return cls(
            **value,
            source_object_version_id=release.source_revision_id,
            links=[
                PublishedArtifactVersionLinkRead(
                    object_version_id=link.revision_id,
                    attempt_object_version_id=link.attempt_revision_id,
                    role=link.role,
                )
                for link in release.links
            ],
        )


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


def public_download_headers() -> dict[str, str]:
    """Released bytes stay downloads and are not cached across moderation changes."""
    return {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="artifact.bin"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Referrer-Policy": "no-referrer",
    }

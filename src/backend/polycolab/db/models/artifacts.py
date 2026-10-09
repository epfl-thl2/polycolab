"""SQLAlchemy entities owned by the artifacts capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    ArtifactResearchRole,
    ArtifactState,
)
from polycolab.entities.time import utc_now


class SqlArtifact(Base):
    """Scoped immutable byte identity with a mutable staging/commit/GC lifecycle."""

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("id", "ownership_scope_id", name="uq_artifacts_id_scope"),
        CheckConstraint("length(sha256) = 64", name="ck_artifacts_sha256_length"),
        CheckConstraint("byte_length >= 0", name="ck_artifacts_byte_length"),
        CheckConstraint(
            "state IN ('STAGING','COMMITTED','DELETING','DELETED')",
            name="ck_artifacts_state",
        ),
        CheckConstraint(
            "(state = 'STAGING' AND committed_at IS NULL AND deleted_at IS NULL) OR "
            "(state = 'COMMITTED' AND verified_at IS NOT NULL AND committed_at IS NOT NULL "
            "AND deleted_at IS NULL) OR "
            "(state = 'DELETING' AND committed_at IS NULL AND deleted_at IS NULL) OR "
            "(state = 'DELETED' AND committed_at IS NULL AND deleted_at IS NOT NULL)",
            name="ck_artifacts_lifecycle",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_length: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(127))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    source_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True
    )
    library_destination_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id")
    )
    environment: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[ArtifactState] = mapped_column(
        Enum(ArtifactState, native_enum=False, length=16), default=ArtifactState.STAGING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlArtifactResearchLink(Base):
    __tablename__ = "artifact_research_links"
    __table_args__ = (
        CheckConstraint(
            "role IN ('SOURCE','INPUT','EVIDENCE','OUTPUT','FORMALIZATION','CERTIFICATE')",
            name="ck_artifact_research_role",
        ),
        UniqueConstraint(
            "artifact_id",
            "revision_id",
            "attempt_revision_id",
            "role",
            name="uq_artifact_research_binding",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), index=True)
    attempt_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_attempt_revisions.revision_id"), nullable=True, index=True
    )
    role: Mapped[ArtifactResearchRole] = mapped_column(
        Enum(ArtifactResearchRole, native_enum=False, length=32)
    )
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlPublicationArtifactMember(Base):
    __tablename__ = "publication_artifact_members"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_artifact_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("artifacts.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


__all__ = [
    "SqlArtifact",
    "SqlArtifactResearchLink",
    "SqlPublicationArtifactMember",
]

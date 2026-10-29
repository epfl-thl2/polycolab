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
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    ArtifactState,
)
from polycolab.entities.time import utc_now


class SqlArtifact(Base):
    """Scoped immutable byte identity with a mutable staging/commit/GC lifecycle."""

    __tablename__ = "artifacts"
    __table_args__ = (
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
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_length: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String(127))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    environment: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    state: Mapped[ArtifactState] = mapped_column(
        Enum(ArtifactState, native_enum=False, length=16), default=ArtifactState.STAGING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "SqlArtifact",
]

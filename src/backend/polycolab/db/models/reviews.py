"""Append-only research assessments, independent of legacy endorsements."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlObjectReview(Base):
    __tablename__ = "object_reviews"
    __table_args__ = (
        Index("ix_object_reviews_current", "object_version_id", "reviewer_id", "created_at", "id"),
        CheckConstraint("actor_kind IN ('HUMAN', 'AGENT')", name="ck_object_reviews_actor"),
        CheckConstraint(
            "(withdrawn AND outcome IS NULL) OR (NOT withdrawn AND outcome IS NOT NULL "
            "AND outcome IN ('REVIEWED', 'SUPPORTS', 'ISSUES_FOUND', 'INCONCLUSIVE'))",
            name="ck_object_reviews_outcome",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_version_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"))
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(String(200))
    actor_kind: Mapped[str] = mapped_column(String(16))
    reviewer_name: Mapped[str] = mapped_column(String(500))
    model_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope: Mapped[str] = mapped_column(String(1000))
    rationale: Mapped[str] = mapped_column(Text)
    evidence_object_version_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    self_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlReviewEvidence(Base):
    __tablename__ = "review_evidence"
    review_id: Mapped[UUID] = mapped_column(ForeignKey("object_reviews.id"), primary_key=True)
    object_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_revisions.id"), primary_key=True
    )


class SqlPublicationReview(Base):
    __tablename__ = "publication_reviews"
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    review_id: Mapped[UUID] = mapped_column(ForeignKey("object_reviews.id"), primary_key=True)

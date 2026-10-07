"""SQLAlchemy entities owned by the catalogue capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlPublicationManifest(Base):
    """Confirmed human publication of one exact, previewed private closure."""

    __tablename__ = "publication_manifests"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ownership_scope_id", "project_id"],
            ["research_scopes.id", "research_scopes.project_id"],
            name="fk_publication_manifest_workspace_scope",
        ),
        CheckConstraint("length(preview_digest) = 64", name="ck_publication_preview_digest"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    preview_digest: Mapped[str] = mapped_column(String(64), unique=True)
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    selection: Mapped[dict[str, object]] = mapped_column(JSON)
    public_fields: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlPublicRelease(Base):
    """A human-selected public exposure of one exact revision."""

    __tablename__ = "public_releases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_revision_id", "ownership_scope_id"],
            ["object_revisions.id", "object_revisions.ownership_scope_id"],
            name="fk_public_releases_revision_scope",
        ),
        UniqueConstraint(
            "ownership_scope_id", "object_revision_id", name="uq_public_releases_scope_revision"
        ),
        CheckConstraint(
            "length(public_fields_digest) = 64", name="ck_public_releases_digest_length"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    object_revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), index=True)
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    publication_manifest_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("publication_manifests.id"), nullable=True, index=True
    )
    projection_version: Mapped[int] = mapped_column(Integer, default=1)
    public_fields: Mapped[dict[str, object]] = mapped_column(JSON)
    public_fields_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlPublicationRevision(Base):
    __tablename__ = "publication_revisions"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_revision_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean)


class SqlPublicationSummary(Base):
    __tablename__ = "publication_summaries"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_summary_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    summary_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_summary_revisions.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class SqlPublicationComment(Base):
    __tablename__ = "publication_comments"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_comment_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    comment_id: Mapped[UUID] = mapped_column(ForeignKey("research_comments.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class SqlPublicationProgress(Base):
    __tablename__ = "publication_progress"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_progress_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    progress_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_progress_updates.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class SqlPublicationRelation(Base):
    __tablename__ = "publication_relations"
    __table_args__ = (
        UniqueConstraint("manifest_id", "position", name="uq_publication_relation_position"),
    )
    manifest_id: Mapped[UUID] = mapped_column(
        ForeignKey("publication_manifests.id"), primary_key=True
    )
    relation_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_version_relationships.id"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)


class SqlCatalogueEntry(Base):
    """Admission of a stable statement identity, independent of ownership."""

    __tablename__ = "catalogue_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["official_revision_id", "id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_catalogue_official_object",
        ),
        Index("ix_catalogue_visible_id", "hidden", "id"),
    )
    id: Mapped[UUID] = mapped_column(ForeignKey("research_objects.id"), primary_key=True)
    official_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("statement_revisions.revision_id")
    )
    admitted_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlCatalogueRevision(Base):
    """Immutable sourced formulation/status for an exact official revision."""

    __tablename__ = "catalogue_revisions"
    __table_args__ = (
        CheckConstraint(
            "(source_identifier IS NOT NULL AND source_version IS NOT NULL "
            "AND source_locator IS NOT NULL) OR (source_identifier IS NULL "
            "AND source_version IS NULL AND source_locator IS NULL)",
            name="ck_catalogue_source_complete",
        ),
        CheckConstraint(
            "(review_rationale IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
            "AND reviewed_at IS NOT NULL) OR (review_rationale IS NULL "
            "AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
            name="ck_catalogue_review_complete",
        ),
        CheckConstraint(
            "source_identifier IS NOT NULL OR review_rationale IS NOT NULL",
            name="ck_catalogue_status_basis",
        ),
        Index(
            "ix_catalogue_source_search",
            text(
                "to_tsvector('simple'::regconfig, (((source_identifier::text || ' '::text) "
                "|| source_version::text) || ' '::text) || source_locator::text)"
            ),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["revision_id", "entry_id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_catalogue_revision_object",
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("statement_revisions.revision_id"), primary_key=True
    )
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("catalogue_entries.id"), index=True)
    source_identifier: Mapped[str | None] = mapped_column(String(2000))
    source_version: Mapped[str | None] = mapped_column(String(500))
    source_locator: Mapped[str | None] = mapped_column(String(1000))
    review_rationale: Mapped[str | None] = mapped_column(Text)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reported_status: Mapped[str] = mapped_column(String(200))
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))


class SqlCatalogueAudit(Base):
    __tablename__ = "catalogue_audit"
    __table_args__ = (
        CheckConstraint(
            "action IN ('ADMIT', 'PROMOTE', 'REVISE', 'HIDE', 'RESTORE')",
            name="ck_catalogue_audit_action",
        ),
        ForeignKeyConstraint(
            ["revision_id", "entry_id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_catalogue_audit_revision",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("catalogue_entries.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"))
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    contribution_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlCommunityDeliveryCursor(Base):
    __tablename__ = "community_delivery_cursors"
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.id"), primary_key=True)
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey("catalogue_entries.id"), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class SqlResearchNotification(Base):
    __tablename__ = "research_notifications"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_id", "entry_id", name="uq_research_notification_delivery"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.id"))
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("catalogue_entries.id"))
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchProgressSummary(Base):
    """Rebuildable bounded exact input snapshot, never authoritative assurance."""

    __tablename__ = "research_progress_summaries"
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("catalogue_entries.id"), primary_key=True)
    revision_ids: Mapped[list[str]] = mapped_column(JSON)
    inputs_digest: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlCatalogueFollow(Base):
    __tablename__ = "catalogue_follows"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogue_entries.id"), primary_key=True, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean)


class SqlCatalogueInterest(Base):
    __tablename__ = "catalogue_interest"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(
        ForeignKey("catalogue_entries.id"), primary_key=True, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean)


class SqlCatalogueModerator(Base):
    __tablename__ = "catalogue_moderators"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean)


class SqlCatalogueModeratorAudit(Base):
    __tablename__ = "catalogue_moderator_audit"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    operator_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    active: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExternalAgentCredential(Base):
    """Opaque delegated identity; historical workspace grants remain immutable."""

    __tablename__ = "external_agent_credentials"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", "sponsor_user_id", name="uq_external_agent_credential_identity"
        ),
        UniqueConstraint("id", "sponsor_user_id", name="uq_external_credential_sponsor"),
        UniqueConstraint("id", "agent_id", "sponsor_user_id", name="uq_external_credential_agent"),
        ForeignKeyConstraint(
            ["agent_id", "sponsor_user_id"],
            ["external_agent_identities.id", "external_agent_identities.sponsor_user_id"],
            name="fk_credential_agent_sponsor",
        ),
        CheckConstraint(
            "(scope_kind = 'ACCOUNT' AND project_id IS NULL) OR "
            "(scope_kind = 'WORKSPACE' AND project_id IS NOT NULL)",
            name="ck_external_credential_scope",
        ),
        CheckConstraint("length(token_digest) = 64", name="ck_external_agent_token_digest"),
        CheckConstraint("request_count >= 0", name="ck_external_agent_request_count"),
        CheckConstraint("mutation_count >= 0", name="ck_external_agent_mutation_count"),
        CheckConstraint("max_requests > 0", name="ck_external_agent_max_requests"),
        CheckConstraint("max_mutations > 0", name="ck_external_agent_max_mutations"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    scope_kind: Mapped[str] = mapped_column(String(16), default="ACCOUNT")
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_agent_identities.id"), index=True
    )
    allow_reviews: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    allow_library_contributions: Mapped[bool] = mapped_column(Boolean, default=False)
    name: Mapped[str] = mapped_column(String(200))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    encrypted_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    wrapped_data_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_key_version: Mapped[str | None] = mapped_column(String(200), nullable=True)

    @property
    def secret_reveal_available(self) -> bool:
        return self.revoked_at is None and all(
            (self.encrypted_secret, self.wrapped_data_key, self.encryption_key_version)
        )

    fixed_rights: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    mutation_count: Mapped[int] = mapped_column(Integer, default=0)
    max_requests: Mapped[int] = mapped_column(Integer)
    max_mutations: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlPublicationManifest",
    "SqlPublicRelease",
    "SqlPublicationRevision",
    "SqlPublicationSummary",
    "SqlPublicationComment",
    "SqlPublicationProgress",
    "SqlPublicationRelation",
    "SqlCatalogueEntry",
    "SqlCatalogueRevision",
    "SqlCatalogueAudit",
    "SqlCommunityDeliveryCursor",
    "SqlResearchNotification",
    "SqlResearchProgressSummary",
    "SqlCatalogueFollow",
    "SqlCatalogueInterest",
    "SqlCatalogueModerator",
    "SqlCatalogueModeratorAudit",
    "SqlExternalAgentCredential",
]

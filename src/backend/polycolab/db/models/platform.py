"""SQLAlchemy entities owned by the platform capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    CanonicalEntityType,
    ContributionActorKind,
    MutationReceiptStatus,
    OutboxEventStatus,
)
from polycolab.entities.time import utc_now


class SqlContributionEnvelope(Base):
    """Append-only provenance envelope for direct and reviewed contributions."""

    __tablename__ = "contribution_envelopes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["external_credential_id", "external_agent_id", "sponsor_user_id"],
            [
                "external_agent_credentials.id",
                "external_agent_credentials.agent_id",
                "external_agent_credentials.sponsor_user_id",
            ],
            name="fk_contribution_stable_actor",
        ),
        ForeignKeyConstraint(
            ["run_id", "session_id", "project_id", "sponsor_user_id", "agent_version_id"],
            [
                "agent_runs.id",
                "agent_runs.session_id",
                "agent_runs.project_id",
                "agent_runs.requested_by_user_id",
                "agent_runs.agent_version_id",
            ],
            name="fk_contribution_run_binding",
        ),
        ForeignKeyConstraint(
            ["context_manifest_id", "run_id", "project_id", "sponsor_user_id", "agent_version_id"],
            [
                "context_manifests.id",
                "context_manifests.run_id",
                "context_manifests.project_id",
                "context_manifests.requested_by_user_id",
                "context_manifests.agent_version_id",
            ],
            name="fk_contribution_manifest_binding",
        ),
        ForeignKeyConstraint(
            ["external_run_id", "external_credential_id", "project_id", "sponsor_user_id"],
            [
                "external_research_runs.id",
                "external_research_runs.credential_id",
                "external_research_runs.project_id",
                "external_research_runs.sponsor_user_id",
            ],
            name="fk_contribution_external_run_binding",
        ),
        CheckConstraint(
            "(proposal_change_id IS NULL AND decided_by_user_id IS NULL) OR "
            "(actor_kind = 'AGENT' AND proposal_change_id IS NOT NULL "
            "AND decided_by_user_id IS NOT NULL)",
            name="ck_contribution_review",
        ),
        CheckConstraint(
            "actor_kind IN ('HUMAN', 'AGENT')", name="ck_contribution_envelopes_actor_kind"
        ),
        CheckConstraint(
            "((actor_kind = 'HUMAN' AND human_user_id IS NOT NULL AND sponsor_user_id IS NULL "
            "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
            "AND context_manifest_id IS NULL AND external_credential_id IS NULL "
            "AND external_run_id IS NULL AND external_agent_id IS NULL) OR "
            "(actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL "
            "AND agent_version_id IS NOT NULL AND run_id IS NOT NULL AND session_id IS NOT NULL "
            "AND context_manifest_id IS NOT NULL AND project_id IS NOT NULL "
            "AND external_credential_id IS NULL AND external_run_id IS NULL "
            "AND external_agent_id IS NULL) OR "
            "(actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL "
            "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
            "AND context_manifest_id IS NULL AND project_id IS NOT NULL "
            "AND external_credential_id IS NOT NULL AND external_run_id IS NOT NULL) OR "
            "(actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL "
            "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
            "AND context_manifest_id IS NULL AND external_run_id IS NULL "
            "AND external_agent_id IS NOT NULL AND external_credential_id IS NOT NULL))",
            name="ck_contribution_envelopes_actor_scope",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_kind: Mapped[ContributionActorKind] = mapped_column(
        Enum(ContributionActorKind, native_enum=False, length=16)
    )
    human_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sponsor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    agent_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_agent_versions.id"), nullable=True
    )
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id"), nullable=True)
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_sessions.id"), nullable=True)
    context_manifest_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("context_manifests.id"), nullable=True
    )
    external_agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_agent_identities.id"), index=True
    )
    external_credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_agent_credentials.id"), nullable=True
    )
    external_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_research_runs.id"), nullable=True
    )
    ownership_scope_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=True, index=True
    )
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    operation: Mapped[str] = mapped_column(String(64))
    proposal_change_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proposal_changes.id"), nullable=True
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    source_event_cursors: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlContributionEntityLink(Base):
    """Typed output references; exactly one FK is populated."""

    __tablename__ = "contribution_entity_links"
    __table_args__ = (
        CheckConstraint(
            "(CASE WHEN object_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN revision_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN relation_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN comment_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_contribution_output_one_target",
        ),
        UniqueConstraint("envelope_id", "object_id", name="uq_output_object"),
        UniqueConstraint("envelope_id", "revision_id", name="uq_output_revision"),
        UniqueConstraint("envelope_id", "relation_id", name="uq_output_relation"),
        UniqueConstraint("envelope_id", "comment_id", name="uq_output_comment"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    envelope_id: Mapped[UUID] = mapped_column(ForeignKey("contribution_envelopes.id"), index=True)
    object_id: Mapped[UUID | None] = mapped_column(ForeignKey("research_objects.id"), nullable=True)
    revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True
    )
    relation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_version_relationships.id"), nullable=True
    )
    comment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_comments.id"), nullable=True
    )
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @property
    def canonical_entity_id(self) -> UUID:
        for value in (self.object_id, self.revision_id, self.relation_id, self.comment_id):
            if value is not None:
                return value
        raise ValueError("missing output target")

    @property
    def canonical_entity_type(self) -> CanonicalEntityType:
        for value, kind in (
            (self.object_id, CanonicalEntityType.RESEARCH_OBJECT),
            (self.revision_id, CanonicalEntityType.OBJECT_REVISION),
            (self.relation_id, CanonicalEntityType.RELATION_ASSERTION),
            (self.comment_id, CanonicalEntityType.RESEARCH_COMMENT),
        ):
            if value is not None:
                return kind
        raise ValueError("missing output target")


class SqlMutationReceipt(Base):
    """Durable idempotency result for top-level canonical mutations."""

    __tablename__ = "mutation_receipts"
    __table_args__ = (
        UniqueConstraint(
            "actor_key", "operation", "idempotency_key_digest", name="uq_mutation_receipts_key"
        ),
        CheckConstraint("status IN ('COMMITTED', 'FAILED')", name="ck_mutation_receipts_status"),
        CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_digest) = 64",
            name="ck_mutation_receipts_digest_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_key: Mapped[str] = mapped_column(String(200), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    idempotency_key_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[MutationReceiptStatus] = mapped_column(
        Enum(MutationReceiptStatus, native_enum=False, length=16)
    )
    resource_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlOutboxEvent(Base):
    """Canonical transaction event for bounded asynchronous consumers."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_claim", "available_at", "created_at", "id"),
        Index("ix_outbox_events_created_at", "created_at", "id"),
        CheckConstraint(
            "status IN ('PENDING', 'CLAIMED', 'DELIVERED', 'FAILED')",
            name="ck_outbox_events_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_outbox_events_attempts"),
        CheckConstraint("length(payload_digest) = 64", name="ck_outbox_events_digest_length"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[UUID] = mapped_column(index=True)
    ownership_scope_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=True, index=True
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    payload_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[OutboxEventStatus] = mapped_column(
        Enum(OutboxEventStatus, native_enum=False, length=16), default=OutboxEventStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlOutboxConsumerReceipt(Base):
    """Per-consumer delivery receipt; canonical events remain immutable."""

    __tablename__ = "outbox_consumer_receipts"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer_name", name="uq_outbox_consumer_receipt"),
        CheckConstraint("attempts >= 0", name="ck_outbox_consumer_receipts_attempts"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("outbox_events.id"), index=True)
    consumer_name: Mapped[str] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


__all__ = [
    "SqlContributionEnvelope",
    "SqlContributionEntityLink",
    "SqlMutationReceipt",
    "SqlOutboxEvent",
    "SqlOutboxConsumerReceipt",
]

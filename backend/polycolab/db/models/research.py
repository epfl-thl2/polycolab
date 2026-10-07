"""SQLAlchemy entities owned by the research capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    select,
    text,
    type_coerce,
)
from sqlalchemy.orm import Mapped, column_property, mapped_column

from polycolab.db.base import Base
from polycolab.db.models.relationships import SqlObjectVersionRelationship, structural_projection
from polycolab.entities.enums import (
    AttemptEvidenceRole,
    CorrespondenceStatus,
    ProvenanceKind,
    RelationType,
    ResearchEntityClass,
    ResearchObjectKind,
    ResearchProgressStatus,
    ResearchScopeKind,
)
from polycolab.entities.object_kinds import KIND_SQL
from polycolab.entities.time import utc_now


class SqlResearchScope(Base):
    """Ownership scope; the commons is not a project or membership group."""

    __tablename__ = "research_scopes"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_research_scopes_project"),
        UniqueConstraint("id", "project_id", name="uq_research_scopes_id_project"),
        Index(
            "uq_research_scopes_commons",
            "scope_kind",
            unique=True,
            postgresql_where=text("scope_kind = 'COMMONS'"),
            sqlite_where=text("scope_kind = 'COMMONS'"),
        ),
        CheckConstraint(
            "(scope_kind = 'COMMONS' AND project_id IS NULL) OR "
            "(scope_kind = 'WORKSPACE' AND project_id IS NOT NULL)",
            name="ck_research_scopes_kind_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_kind: Mapped[ResearchScopeKind] = mapped_column(
        Enum(ResearchScopeKind, native_enum=False, length=16)
    )
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchObject(Base):
    """Stable project-scoped identity; revision content never lives on this row."""

    __tablename__ = "research_objects"

    __table_args__ = (
        CheckConstraint(
            "kind IN ('PROBLEM', 'DEFINITION', 'CLAIM', 'PROOF', 'PROOF_SKETCH', 'ATTEMPT', "
            "'COUNTEREXAMPLE', 'NOTE', 'IDEA', 'DISCUSSION', 'FORMALIZATION', 'COMPUTATION')",
            name="ck_research_objects_kind",
        ),
        CheckConstraint(
            "provenance_kind IN ('HUMAN_DIRECT', 'AGENT_PROPOSAL', 'AGENT_DIRECT')",
            name="ck_research_objects_provenance_kind",
        ),
        UniqueConstraint("id", "ownership_scope_id", name="uq_research_objects_id_scope"),
        # This ensures the selected current revision belongs to this exact
        # stable object and project, rather than merely being some revision ID.
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_research_objects_current_revision",
            use_alter=True,
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    entity_class: Mapped[ResearchEntityClass] = mapped_column(
        Enum(ResearchEntityClass, native_enum=False, length=16)
    )
    project_id: Mapped[UUID] = column_property(
        type_coerce(
            select(SqlResearchScope.project_id)
            .where(SqlResearchScope.id == ownership_scope_id)
            .scalar_subquery(),
            Uuid(as_uuid=True),
        )
    )
    kind: Mapped[ResearchObjectKind] = mapped_column(
        Enum(ResearchObjectKind, native_enum=False, length=32)
    )
    canonical_kind: Mapped[str] = mapped_column(
        String(32), Computed(KIND_SQL, persisted=True), index=True
    )
    # Set in the same transaction as the initial/new revision. It is nullable
    # briefly inside that transaction before revision one is inserted.
    current_revision_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provenance_kind: Mapped[ProvenanceKind] = mapped_column(
        Enum(ProvenanceKind, native_enum=False, length=32), default=ProvenanceKind.HUMAN_DIRECT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlObjectRevision(Base):
    __tablename__ = "object_revisions"
    __table_args__ = (
        Index(
            "ix_revision_search",
            text("to_tsvector('simple'::regconfig, (title::text || ' '::text) || content_md)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        ForeignKeyConstraint(
            ["object_id", "ownership_scope_id"],
            ["research_objects.id", "research_objects.ownership_scope_id"],
            name="fk_revision_object_scope",
        ),
        UniqueConstraint("id", "ownership_scope_id", name="uq_object_revisions_id_scope"),
        CheckConstraint(
            "provenance_kind IN ('HUMAN_DIRECT', 'AGENT_PROPOSAL', 'AGENT_DIRECT')",
            name="ck_object_revisions_provenance_kind",
        ),
        CheckConstraint("number > 0 AND schema_version > 0", name="ck_revision_versions"),
        UniqueConstraint("object_id", "number", name="uq_object_revisions_number"),
        UniqueConstraint("id", "object_id", name="uq_object_revisions_id_object"),
        ForeignKeyConstraint(
            ["object_id"],
            ["research_objects.id"],
            name="fk_object_revisions_object_project",
        ),
        ForeignKeyConstraint(
            ["base_revision_id", "object_id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_object_revisions_base_object_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = column_property(
        type_coerce(
            select(SqlResearchScope.project_id)
            .where(SqlResearchScope.id == ownership_scope_id)
            .scalar_subquery(),
            Uuid(as_uuid=True),
        )
    )
    object_id: Mapped[UUID] = mapped_column(index=True)
    semantic_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    number: Mapped[int] = mapped_column(Integer)
    # A title is revision content, so a later edit cannot rewrite its old meaning.
    title: Mapped[str] = mapped_column(String(500))
    content_md: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provenance_kind: Mapped[ProvenanceKind] = mapped_column(
        Enum(ProvenanceKind, native_enum=False, length=32), default=ProvenanceKind.HUMAN_DIRECT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRelationAssertion(Base):
    """Legacy read adapter for independently attributed canonical declarations."""

    __table__ = (
        select(
            SqlObjectVersionRelationship.id,
            SqlObjectVersionRelationship.ownership_scope_id,
            func.coalesce(
                SqlObjectVersionRelationship.source_object_version_id,
                SqlObjectVersionRelationship.first_object_version_id,
            ).label("source_revision_id"),
            func.coalesce(
                SqlObjectVersionRelationship.target_object_version_id,
                SqlObjectVersionRelationship.second_object_version_id,
            ).label("target_revision_id"),
            type_coerce(
                SqlObjectVersionRelationship.relationship_type,
                Enum(RelationType, native_enum=False, length=32),
            ).label("relation_type"),
            func.coalesce(SqlObjectVersionRelationship.description, "").label("rationale"),
            SqlObjectVersionRelationship.contribution_id,
            SqlObjectVersionRelationship.created_by_user_id,
            SqlObjectVersionRelationship.provenance_kind,
            SqlObjectVersionRelationship.created_at,
        )
        .where(SqlObjectVersionRelationship.binding == "DECLARATION")
        .subquery()
    )

    id: Mapped[UUID]
    ownership_scope_id: Mapped[UUID]
    source_revision_id: Mapped[UUID]
    target_revision_id: Mapped[UUID]
    relation_type: Mapped[RelationType]
    rationale: Mapped[str]
    contribution_id: Mapped[UUID]
    created_by_user_id: Mapped[UUID]
    provenance_kind: Mapped[ProvenanceKind]
    created_at: Mapped[datetime]
    project_id: Mapped[UUID | None] = column_property(
        select(SqlResearchScope.project_id)
        .where(SqlResearchScope.id == __table__.c.ownership_scope_id)
        .scalar_subquery()
    )


class SqlResearchComment(Base):
    """Immutable member discussion, grouped by object but pinned to a revision."""

    __tablename__ = "research_comments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "ownership_scope_id"],
            ["research_objects.id", "research_objects.ownership_scope_id"],
            name="fk_comment_object_scope",
        ),
        CheckConstraint(
            "provenance_kind IN ('HUMAN_DIRECT', 'AGENT_PROPOSAL', 'AGENT_DIRECT')",
            name="ck_research_comments_provenance_kind",
        ),
        ForeignKeyConstraint(
            ["revision_id", "object_id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_research_comments_revision_object_project",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    project_id: Mapped[UUID] = column_property(
        type_coerce(
            select(SqlResearchScope.project_id)
            .where(SqlResearchScope.id == ownership_scope_id)
            .scalar_subquery(),
            Uuid(as_uuid=True),
        )
    )
    object_id: Mapped[UUID] = mapped_column(index=True)
    revision_id: Mapped[UUID] = mapped_column(index=True)
    body_md: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provenance_kind: Mapped[ProvenanceKind] = mapped_column(
        Enum(ProvenanceKind, native_enum=False, length=32), default=ProvenanceKind.HUMAN_DIRECT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlStatementRevision(Base):
    __tablename__ = "statement_revisions"
    __table_args__ = (
        CheckConstraint("kind IN ('PROBLEM', 'DEFINITION', 'CLAIM')", name="ck_statement_kind"),
    )
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    assumptions_md: Mapped[str] = mapped_column(Text, default="")
    reported_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)


class SqlRecordRevision(Base):
    __tablename__ = "record_revisions"
    __table_args__ = (
        Index(
            "ix_record_explanation_search",
            text("to_tsvector('simple', coalesce(explanation_md, ''))"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint(
            "kind IN ('NOTE', 'IDEA', 'ATTEMPT', 'PROOF', 'PROOF_SKETCH', 'DISCUSSION', "
            "'COUNTEREXAMPLE', 'FORMALIZATION', 'COMPUTATION')",
            name="ck_record_kind",
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    assumptions_md: Mapped[str] = mapped_column(Text, default="")
    reported_outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    explanation_md: Mapped[str | None] = mapped_column(Text, nullable=True)


class SqlRecordStatementLink(Base):
    """Read-only typed projection of canonical structural relationships."""

    _links = structural_projection("ATTACHMENT", "record_revision_id", "statement_revision_id")
    __table__ = (
        select(_links)
        .where(_links.c.record_revision_id.in_(select(SqlRecordRevision.revision_id)))
        .subquery()
    )
    __mapper_args__ = {
        "primary_key": [__table__.c.record_revision_id, __table__.c.statement_revision_id]
    }
    record_revision_id: Mapped[UUID]
    statement_revision_id: Mapped[UUID]


class SqlProofSketchMetadata(Base):
    """Exact conclusion and reported progress for one proof-sketch revision."""

    __tablename__ = "proof_sketch_revisions"
    __table_args__ = (
        CheckConstraint(
            "reported_progress IN ('POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED')",
            name="ck_proof_sketch_progress",
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("record_revisions.revision_id"), primary_key=True
    )
    reported_progress: Mapped[ResearchProgressStatus] = mapped_column(
        Enum(ResearchProgressStatus, native_enum=False, length=16)
    )


class SqlProofSketchRevision(Base):
    """Complete read projection; only reported progress lives in its metadata table."""

    _conclusion = structural_projection(
        "CONCLUSION", "sketch_revision_id", "conclusion_revision_id"
    )
    __table__ = (
        select(SqlProofSketchMetadata.__table__, _conclusion.c.conclusion_revision_id)
        .outerjoin(
            _conclusion, _conclusion.c.sketch_revision_id == SqlProofSketchMetadata.revision_id
        )
        .subquery()
    )
    __mapper_args__ = {"primary_key": [__table__.c.revision_id]}
    revision_id: Mapped[UUID]
    conclusion_revision_id: Mapped[UUID]
    reported_progress: Mapped[ResearchProgressStatus]


class SqlProofSketchPremise(Base):
    """Read-only typed projection of canonical structural relationships."""

    __table__ = structural_projection("PREMISE", "sketch_revision_id", "premise_revision_id")
    __mapper_args__ = {
        "primary_key": [__table__.c.sketch_revision_id, __table__.c.premise_revision_id]
    }
    sketch_revision_id: Mapped[UUID]
    premise_revision_id: Mapped[UUID]
    position: Mapped[int]


class SqlResearchAttemptMetadata(Base):
    """Attributable activity against one exact non-attempt research revision."""

    __tablename__ = "research_attempt_revisions"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED')",
            name="ck_research_attempt_outcome",
        ),
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("record_revisions.revision_id"), primary_key=True
    )
    outcome: Mapped[ResearchProgressStatus] = mapped_column(
        Enum(ResearchProgressStatus, native_enum=False, length=16)
    )
    findings_md: Mapped[str] = mapped_column(Text)


class SqlResearchAttemptRevision(Base):
    """Complete read projection with exact targets derived from canonical relationships."""

    _target = structural_projection("TARGET", "attempt_revision_id", "target_revision_id")
    _result = structural_projection("RESULT", "attempt_revision_id", "result_revision_id")
    __table__ = (
        select(
            SqlResearchAttemptMetadata.__table__,
            _target.c.target_revision_id,
            SqlObjectRevision.object_id.label("target_object_id"),
            _result.c.result_revision_id,
        )
        .outerjoin(_target, _target.c.attempt_revision_id == SqlResearchAttemptMetadata.revision_id)
        .outerjoin(SqlObjectRevision, SqlObjectRevision.id == _target.c.target_revision_id)
        .outerjoin(_result, _result.c.attempt_revision_id == SqlResearchAttemptMetadata.revision_id)
        .subquery()
    )
    __mapper_args__ = {"primary_key": [__table__.c.revision_id]}
    revision_id: Mapped[UUID]
    target_revision_id: Mapped[UUID]
    target_object_id: Mapped[UUID]
    result_revision_id: Mapped[UUID | None]
    outcome: Mapped[ResearchProgressStatus]
    findings_md: Mapped[str]


class SqlAttemptEvidenceLink(Base):
    """Read-only typed projection of canonical structural relationships."""

    __table__ = structural_projection("EVIDENCE", "attempt_revision_id", "evidence_revision_id")
    __mapper_args__ = {
        "primary_key": [__table__.c.attempt_revision_id, __table__.c.evidence_revision_id]
    }
    attempt_revision_id: Mapped[UUID]
    evidence_revision_id: Mapped[UUID]
    position: Mapped[int]
    role: Mapped[AttemptEvidenceRole]


class SqlHumanNote(Base):
    """One human-owned private note stream associated with a research object."""

    __tablename__ = "human_notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "ownership_scope_id"],
            ["research_objects.id", "research_objects.ownership_scope_id"],
            name="fk_human_note_object_scope",
        ),
        ForeignKeyConstraint(
            ["current_revision_id", "object_id"],
            ["human_note_revisions.id", "human_note_revisions.object_id"],
            name="fk_human_note_current_revision",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ).ddl_if(dialect="postgresql"),
    )
    object_id: Mapped[UUID] = mapped_column(primary_key=True)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    current_revision_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlHumanNoteRevision(Base):
    __tablename__ = "human_note_revisions"
    __table_args__ = (
        UniqueConstraint("object_id", "number", name="uq_human_note_revision_number"),
        UniqueConstraint("id", "object_id", name="uq_human_note_revision_id_object"),
        ForeignKeyConstraint(
            ["base_revision_id", "object_id"],
            ["human_note_revisions.id", "human_note_revisions.object_id"],
            name="fk_human_note_revision_base",
        ),
        CheckConstraint("number > 0", name="ck_human_note_revision_number"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("human_notes.object_id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    base_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    body_md: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchSummary(Base):
    """One canonical authored-summary stream associated with a research object."""

    __tablename__ = "research_summaries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["object_id", "ownership_scope_id"],
            ["research_objects.id", "research_objects.ownership_scope_id"],
            name="fk_research_summary_object_scope",
        ),
        ForeignKeyConstraint(
            ["current_revision_id", "object_id"],
            ["research_summary_revisions.id", "research_summary_revisions.object_id"],
            name="fk_research_summary_current_revision",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ).ddl_if(dialect="postgresql"),
    )
    object_id: Mapped[UUID] = mapped_column(primary_key=True)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    current_revision_id: Mapped[UUID | None] = mapped_column(index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchSummaryRevision(Base):
    __tablename__ = "research_summary_revisions"
    __table_args__ = (
        UniqueConstraint("object_id", "number", name="uq_research_summary_revision_number"),
        UniqueConstraint("id", "object_id", name="uq_research_summary_revision_id_object"),
        ForeignKeyConstraint(
            ["base_revision_id", "object_id"],
            ["research_summary_revisions.id", "research_summary_revisions.object_id"],
            name="fk_research_summary_revision_base",
        ),
        CheckConstraint("number > 0", name="ck_research_summary_revision_number"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("research_summaries.object_id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    base_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    body_md: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlSummarySourceRevision(Base):
    __tablename__ = "summary_source_revisions"
    __table_args__ = (
        UniqueConstraint("summary_revision_id", "position", name="uq_summary_source_position"),
        CheckConstraint("position >= 0", name="ck_summary_source_position"),
    )
    summary_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_summary_revisions.id"), primary_key=True
    )
    source_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("object_revisions.id"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer)


class SqlResearchProgressUpdate(Base):
    """Append-only reported activity pinned to one exact object revision."""

    __tablename__ = "research_progress_updates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('POTENTIAL', 'PARTIAL', 'COMPLETE', 'STALLED', 'FAILED')",
            name="ck_research_progress_status",
        ),
        CheckConstraint(
            "provenance_kind IN ('HUMAN_DIRECT', 'AGENT_PROPOSAL', 'AGENT_DIRECT')",
            name="ck_research_progress_provenance",
        ),
        ForeignKeyConstraint(
            ["object_id", "ownership_scope_id"],
            ["research_objects.id", "research_objects.ownership_scope_id"],
            name="fk_research_progress_object_scope",
        ),
        ForeignKeyConstraint(
            ["revision_id", "object_id"],
            ["object_revisions.id", "object_revisions.object_id"],
            name="fk_research_progress_revision_object",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    ownership_scope_id: Mapped[UUID] = mapped_column(
        ForeignKey("research_scopes.id"), nullable=False, index=True
    )
    object_id: Mapped[UUID] = mapped_column(index=True)
    revision_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[ResearchProgressStatus] = mapped_column(
        Enum(ResearchProgressStatus, native_enum=False, length=16)
    )
    detail_md: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provenance_kind: Mapped[ProvenanceKind] = mapped_column(
        Enum(ProvenanceKind, native_enum=False, length=32)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRevisionEndorsement(Base):
    """Append-only human endorsement state for one exact revision."""

    __tablename__ = "revision_endorsements"
    __table_args__ = (
        Index("ix_rev_endorse_hist", "revision_id", "created_at", "id"),
        Index(
            "ix_rev_endorse_current",
            "revision_id",
            "created_by_user_id",
            "created_at",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean)
    rationale: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlCorrespondenceAssessment(Base):
    """Append-only assessment kept distinct from formal or computational checks."""

    __tablename__ = "correspondence_assessments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('MATCHES', 'PARTIAL', 'MISMATCH', 'UNASSESSED')",
            name="ck_correspondence_status",
        ),
        Index("ix_corr_assess_hist", "revision_id", "created_at", "id"),
        Index(
            "ix_corr_assess_current",
            "revision_id",
            "created_by_user_id",
            "statement_revision_id",
            "created_at",
            "id",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("record_revisions.revision_id"), index=True
    )
    statement_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("statement_revisions.revision_id"), index=True
    )
    status: Mapped[CorrespondenceStatus] = mapped_column(
        Enum(CorrespondenceStatus, native_enum=False, length=16)
    )
    rationale: Mapped[str] = mapped_column(Text)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchAttachment(Base):
    """Read-only typed projection of canonical structural relationships."""

    __table__ = structural_projection("ATTACHMENT", "revision_id", "statement_revision_id")
    __mapper_args__ = {"primary_key": [__table__.c.revision_id, __table__.c.statement_revision_id]}
    revision_id: Mapped[UUID]
    statement_revision_id: Mapped[UUID]


class SqlRecordModeration(Base):
    __tablename__ = "record_moderation"
    object_id: Mapped[UUID] = mapped_column(ForeignKey("research_objects.id"), primary_key=True)
    hidden: Mapped[bool] = mapped_column(Boolean)


class SqlRecordModerationAudit(Base):
    __tablename__ = "record_moderation_audit"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("research_objects.id"), index=True)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"))
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    hidden: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlCorrectionSuggestion(Base):
    __tablename__ = "correction_suggestions"
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    target_revision_id: Mapped[UUID] = mapped_column(ForeignKey("statement_revisions.revision_id"))
    proposed: Mapped[dict[str, object]] = mapped_column(JSON)


class SqlCorrectionDecision(Base):
    __tablename__ = "correction_decisions"
    suggestion_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("correction_suggestions.revision_id"), primary_key=True
    )
    action: Mapped[str] = mapped_column(String(32))
    decided_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decided_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True
    )
    request_digest: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlPublicResearchAnchor(Base):
    """Public exposure depends on every admitted ancestor remaining visible."""

    __tablename__ = "public_research_anchors"
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"), primary_key=True)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("catalogue_entries.id"), primary_key=True)


class SqlWorkspaceReference(Base):
    """Private identity pointing to a public object without copying its research."""

    __tablename__ = "workspace_references"
    __table_args__ = (
        UniqueConstraint("project_id", "object_id", name="uq_workspace_reference_target"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    object_id: Mapped[UUID] = mapped_column(ForeignKey("research_objects.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlWorkspaceReferenceVersion(Base):
    __tablename__ = "workspace_reference_versions"
    __table_args__ = (
        UniqueConstraint("reference_id", "number", name="uq_workspace_reference_number"),
        CheckConstraint("number > 0", name="ck_workspace_reference_number"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference_id: Mapped[UUID] = mapped_column(ForeignKey("workspace_references.id"))
    number: Mapped[int] = mapped_column(Integer)
    base_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workspace_reference_versions.id"), nullable=True
    )
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("object_revisions.id"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlResearchScope",
    "SqlResearchObject",
    "SqlObjectRevision",
    "SqlRelationAssertion",
    "SqlResearchComment",
    "SqlStatementRevision",
    "SqlRecordRevision",
    "SqlRecordStatementLink",
    "SqlProofSketchRevision",
    "SqlProofSketchPremise",
    "SqlResearchAttemptRevision",
    "SqlAttemptEvidenceLink",
    "SqlHumanNote",
    "SqlHumanNoteRevision",
    "SqlResearchSummary",
    "SqlResearchSummaryRevision",
    "SqlSummarySourceRevision",
    "SqlResearchProgressUpdate",
    "SqlRevisionEndorsement",
    "SqlCorrespondenceAssessment",
    "SqlResearchAttachment",
    "SqlRecordModeration",
    "SqlRecordModerationAudit",
    "SqlCorrectionSuggestion",
    "SqlCorrectionDecision",
    "SqlPublicResearchAnchor",
    "SqlWorkspaceReference",
    "SqlWorkspaceReferenceVersion",
]

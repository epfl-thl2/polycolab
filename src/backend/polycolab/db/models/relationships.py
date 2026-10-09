"""Canonical storage for immutable exact-object-version relationships."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    select,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.selectable import Subquery

from polycolab.db.base import Base
from polycolab.entities.enums import AttemptEvidenceRole, ProvenanceKind
from polycolab.entities.time import utc_now


class SqlObjectVersionRelationship(Base):
    __tablename__ = "object_version_relationships"
    __table_args__ = (
        CheckConstraint(
            "(direction = 'UNIDIRECTIONAL' AND source_object_version_id IS NOT NULL "
            "AND target_object_version_id IS NOT NULL AND first_object_version_id IS NULL "
            "AND second_object_version_id IS NULL) OR "
            "(direction = 'BIDIRECTIONAL' AND source_object_version_id IS NULL "
            "AND target_object_version_id IS NULL AND first_object_version_id IS NOT NULL "
            "AND second_object_version_id IS NOT NULL "
            "AND first_object_version_id <= second_object_version_id)",
            name="ck_relationship_endpoints",
        ),
        CheckConstraint(
            "(binding = 'STRUCTURAL' AND direction = 'UNIDIRECTIONAL' "
            "AND relationship_type IN ('ATTACHMENT','CONCLUSION','PREMISE','TARGET',"
            "'EVIDENCE','RESULT')) OR (binding = 'DECLARATION' AND "
            "((direction = 'BIDIRECTIONAL' AND relationship_type = 'EQUIVALENT_TO') OR "
            "(direction = 'UNIDIRECTIONAL' AND relationship_type IN "
            "('DEPENDS_ON','PROVES','ATTEMPTS','REFUTES','USES','IMPLIES'))))",
            name="ck_relationship_type_binding",
        ),
        CheckConstraint(
            "(relationship_type IN ('PREMISE','EVIDENCE') AND position IS NOT NULL "
            "AND position >= 0) OR (relationship_type NOT IN ('PREMISE','EVIDENCE') "
            "AND position IS NULL)",
            name="ck_relationship_position",
        ),
        CheckConstraint(
            "(relationship_type = 'EVIDENCE' AND evidence_role IS NOT NULL "
            "AND evidence_role IN ('INPUT','SUPPORTS','CONTRADICTS','OUTPUT')) OR "
            "(relationship_type <> 'EVIDENCE' AND evidence_role IS NULL)",
            name="ck_relationship_evidence_role",
        ),
        CheckConstraint(
            "provenance_kind IN ('HUMAN_DIRECT','AGENT_PROPOSAL','AGENT_DIRECT')",
            name="ck_relationship_provenance",
        ),
        Index(
            "uq_structural_relationship",
            "source_object_version_id",
            "relationship_type",
            "target_object_version_id",
            unique=True,
            postgresql_where=text("binding = 'STRUCTURAL'"),
            sqlite_where=text("binding = 'STRUCTURAL'"),
        ),
        Index(
            "uq_structural_position",
            "source_object_version_id",
            "relationship_type",
            "position",
            unique=True,
            postgresql_where=text("position IS NOT NULL"),
            sqlite_where=text("position IS NOT NULL"),
        ),
        Index(
            "uq_structural_single_target",
            "source_object_version_id",
            "relationship_type",
            unique=True,
            postgresql_where=text("relationship_type IN ('CONCLUSION','TARGET','RESULT')"),
            sqlite_where=text("relationship_type IN ('CONCLUSION','TARGET','RESULT')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    relationship_type: Mapped[str] = mapped_column(String(32))
    binding: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(16))
    source_object_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True, index=True
    )
    target_object_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True, index=True
    )
    first_object_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True, index=True
    )
    second_object_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("object_revisions.id"), nullable=True, index=True
    )
    position: Mapped[int | None] = mapped_column(nullable=True)
    evidence_role: Mapped[AttemptEvidenceRole | None] = mapped_column(
        Enum(AttemptEvidenceRole, native_enum=False, length=16), nullable=True
    )
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    contribution_id: Mapped[UUID] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    provenance_kind: Mapped[ProvenanceKind] = mapped_column(
        Enum(ProvenanceKind, native_enum=False, length=32)
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


def structural_projection(role: str, source_name: str, target_name: str) -> Subquery:
    """Read-only typed access to canonical rows; not a second persisted copy."""
    row = SqlObjectVersionRelationship
    columns = [
        row.source_object_version_id.label(source_name),
        row.target_object_version_id.label(target_name),
    ]
    query = select(*columns)
    if role in {"PREMISE", "EVIDENCE"}:
        query = query.add_columns(row.position)
    if role == "EVIDENCE":
        query = query.add_columns(row.evidence_role.label("role"))
    return query.where(row.binding == "STRUCTURAL", row.relationship_type == role).subquery()

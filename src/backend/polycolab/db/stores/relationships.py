"""Insert canonical relationship rows without owning the caller's transaction."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.db.models.research import SqlObjectRevision, SqlRelationAssertion
from polycolab.entities.enums import AttemptEvidenceRole, ProvenanceKind, RelationType
from polycolab.entities.research import StructuralRole


def add_structural_relationship(
    session: Session,
    *,
    source_object_version_id: UUID,
    target_object_version_id: UUID,
    relationship_type: StructuralRole,
    position: int | None = None,
    evidence_role: AttemptEvidenceRole | None = None,
) -> SqlObjectVersionRelationship:
    source = session.get(SqlObjectRevision, source_object_version_id)
    if source is None:
        raise ValueError("structural source version does not exist")
    row = SqlObjectVersionRelationship(
        binding="STRUCTURAL",
        direction="UNIDIRECTIONAL",
        relationship_type=relationship_type.value,
        source_object_version_id=source.id,
        target_object_version_id=target_object_version_id,
        ownership_scope_id=source.ownership_scope_id,
        contribution_id=source.contribution_id,
        created_by_user_id=source.created_by_user_id,
        provenance_kind=source.provenance_kind,
        created_at=source.created_at,
        position=position,
        evidence_role=evidence_role,
    )
    session.add(row)
    return row


def add_declaration(
    session: Session,
    *,
    source_revision_id: UUID,
    target_revision_id: UUID,
    relation_type: RelationType,
    ownership_scope_id: UUID,
    contribution_id: UUID,
    created_by_user_id: UUID,
    provenance_kind: ProvenanceKind,
    rationale: str | None,
) -> SqlRelationAssertion:
    bidirectional = relation_type is RelationType.EQUIVALENT_TO
    first, second = sorted((source_revision_id, target_revision_id))
    row = SqlObjectVersionRelationship(
        binding="DECLARATION",
        direction="BIDIRECTIONAL" if bidirectional else "UNIDIRECTIONAL",
        relationship_type=relation_type.value,
        source_object_version_id=None if bidirectional else source_revision_id,
        target_object_version_id=None if bidirectional else target_revision_id,
        first_object_version_id=first if bidirectional else None,
        second_object_version_id=second if bidirectional else None,
        ownership_scope_id=ownership_scope_id,
        contribution_id=contribution_id,
        created_by_user_id=created_by_user_id,
        provenance_kind=provenance_kind,
        description=rationale,
    )
    session.add(row)
    session.flush()
    result = session.get(SqlRelationAssertion, row.id)
    assert result is not None
    return result

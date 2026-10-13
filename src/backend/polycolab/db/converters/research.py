"""Build immutable research values from already loaded rows; never issue SQL."""

from collections.abc import Sequence
from datetime import datetime
from typing import TypedDict
from uuid import UUID

from polycolab.db.converters.time import timestamp
from polycolab.db.models import (
    SqlContributionEnvelope,
    SqlObjectRevision,
    SqlProofSketchRevision,
    SqlRecordRevision,
    SqlResearchAttemptRevision,
    SqlResearchObject,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.entities.enums import RelationType, ResearchObjectKind
from polycolab.entities.research import (
    KIND_DEFINITIONS,
    AttemptContent,
    AttemptVersion,
    BidirectionalRelationship,
    ObjectVersionRelationship,
    ProofSketchContent,
    RelationshipBinding,
    ResearchAttribution,
    ResearchContent,
    ResearchObjectVersion,
    StructuralRole,
    UnidirectionalRelationship,
)
from polycolab.research.store import ResearchObjectSnapshot


class _RelationshipFields(TypedDict):
    id: UUID
    binding: RelationshipBinding
    relationship_type: StructuralRole | RelationType
    ownership_scope_id: UUID
    description: str | None
    created_at: datetime
    authorship: ResearchAttribution


class _ContentFields(TypedDict):
    title: str
    content_md: str
    assumptions_md: str
    reported_outcome: str | None
    explanation_md: str | None


class _VersionFields(TypedDict):
    id: UUID
    object_id: UUID
    kind: ResearchObjectKind
    number: int
    previous_object_version_id: UUID | None
    schema_version: int
    change_summary: str | None
    created_at: datetime
    authorship: ResearchAttribution
    structural_relationships: tuple[UnidirectionalRelationship, ...]


def attribution(
    envelope: SqlContributionEnvelope,
    author: SqlUser,
    *,
    agent_id: UUID | None,
    agent_display_name: str | None,
) -> ResearchAttribution:
    return ResearchAttribution(
        contribution_id=envelope.id,
        actor_kind=envelope.actor_kind,
        author_display_name=author.display_name,
        author_user_id=envelope.human_user_id,
        agent_id=agent_id,
        sponsor_user_id=envelope.sponsor_user_id,
        agent_display_name=agent_display_name,
        author_username=author.username if envelope.human_user_id == author.id else None,
        sponsor_username=author.username if envelope.sponsor_user_id == author.id else None,
    )


def relationship(
    row: SqlObjectVersionRelationship, authorship: ResearchAttribution
) -> ObjectVersionRelationship:
    fields: _RelationshipFields = dict(
        id=row.id,
        binding=RelationshipBinding(row.binding),
        relationship_type=StructuralRole(row.relationship_type)
        if row.binding == "STRUCTURAL"
        else RelationType(row.relationship_type),
        ownership_scope_id=row.ownership_scope_id,
        description=row.description,
        created_at=timestamp(row.created_at),
        authorship=authorship,
    )
    if row.direction == "BIDIRECTIONAL":
        if row.first_object_version_id is None or row.second_object_version_id is None:
            raise ValueError("bidirectional relationship is missing endpoints")
        return BidirectionalRelationship(
            **fields,
            first_object_version_id=row.first_object_version_id,
            second_object_version_id=row.second_object_version_id,
        )
    if row.source_object_version_id is None or row.target_object_version_id is None:
        raise ValueError("directed relationship is missing endpoints")
    return UnidirectionalRelationship(
        **fields,
        source_object_version_id=row.source_object_version_id,
        target_object_version_id=row.target_object_version_id,
        position=row.position,
        evidence_role=row.evidence_role,
    )


def research_object(
    row: SqlResearchObject, authorship: ResearchAttribution
) -> ResearchObjectSnapshot:
    if row.current_revision_id is None:
        raise ValueError("research object has no committed current version")
    return KIND_DEFINITIONS[row.kind].object_type(
        id=row.id,
        ownership_scope_id=row.ownership_scope_id,
        kind=row.kind,
        authorship=authorship,
        created_at=timestamp(row.created_at),
        current_object_version_id=row.current_revision_id,
    )


def version(
    revision: SqlObjectRevision,
    obj: SqlResearchObject,
    metadata: SqlStatementRevision | SqlRecordRevision,
    authorship: ResearchAttribution,
    relationships: Sequence[SqlObjectVersionRelationship],
    *,
    proof: SqlProofSketchRevision | None,
    attempt: SqlResearchAttemptRevision | None,
) -> ResearchObjectVersion:
    content_fields: _ContentFields = dict(
        title=revision.title,
        content_md=revision.content_md,
        assumptions_md=metadata.assumptions_md,
        reported_outcome=metadata.reported_outcome,
        explanation_md=metadata.explanation_md,
    )
    fields: _VersionFields = dict(
        id=revision.id,
        object_id=obj.id,
        kind=obj.kind,
        number=revision.number,
        previous_object_version_id=revision.base_revision_id,
        schema_version=revision.schema_version,
        change_summary=revision.rationale,
        created_at=timestamp(revision.created_at),
        authorship=authorship,
        structural_relationships=tuple(
            UnidirectionalRelationship(
                id=row.id,
                source_object_version_id=revision.id,
                target_object_version_id=row.target_object_version_id,
                relationship_type=StructuralRole(row.relationship_type),
                binding=RelationshipBinding.STRUCTURAL,
                ownership_scope_id=row.ownership_scope_id,
                authorship=authorship,
                created_at=timestamp(row.created_at),
                position=row.position,
                evidence_role=row.evidence_role,
                description=row.description,
            )
            for row in relationships
            if row.target_object_version_id is not None
        ),
    )
    if obj.kind is ResearchObjectKind.ATTEMPT:
        return AttemptVersion(
            **fields,
            content=AttemptContent(
                **content_fields,
                outcome=attempt.outcome if attempt else None,
                findings_md=attempt.findings_md if attempt else None,
            ),
            target_object_id=attempt.target_object_id if attempt else None,
            legacy_unstructured=attempt is None,
        )
    content: ResearchContent
    if obj.kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}:
        content = ProofSketchContent(
            **content_fields, reported_progress=proof.reported_progress if proof else None
        )
    else:
        content = ResearchContent(**content_fields)
    return KIND_DEFINITIONS[obj.kind].version_type(**fields, content=content)

"""HTTP schemas owned by the research capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field, model_validator

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.catalogue.schemas import CatalogueRevise, CatalogueSource
from polycolab.entities.enums import (
    AttemptEvidenceRole,
    ProvenanceKind,
    RelationType,
    ResearchObjectKind,
    ResearchProgressStatus,
)
from polycolab.entities.research import KIND_DEFINITIONS, StructuralRole


class VersionRelationship(ApiModel):
    """Legacy HTTP structural projection; canonical entities carry IDs and authorship."""

    target_version_id: UUID
    role: StructuralRole
    position: int | None = None
    evidence_role: AttemptEvidenceRole | None = None


class ProofStructureRequest(RequestModel):
    conclusion_revision_id: UUID
    premise_revision_ids: list[UUID] = Field(default_factory=list, max_length=32)
    reported_progress: ResearchProgressStatus

    @model_validator(mode="after")
    def coherent(self) -> ProofStructureRequest:
        if len(set(self.premise_revision_ids)) != len(self.premise_revision_ids):
            raise ValueError("duplicate proof premises")
        if self.conclusion_revision_id in self.premise_revision_ids:
            raise ValueError("a conclusion cannot be its own premise")
        return self


class AttemptEvidenceRequest(RequestModel):
    revision_id: UUID
    role: AttemptEvidenceRole


class ResearchAttemptRequest(RequestModel):
    target_revision_id: UUID
    outcome: ResearchProgressStatus
    findings_md: str = Field(min_length=1, max_length=50_000)
    evidence: list[AttemptEvidenceRequest] = Field(default_factory=list, max_length=64)
    result_revision_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self) -> ResearchAttemptRequest:
        evidence_ids = [item.revision_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("duplicate attempt evidence")
        if self.result_revision_id == self.target_revision_id:
            raise ValueError("attempt result must be newer than its target")
        return self


class ResearchObjectCreate(RequestModel):
    kind: ResearchObjectKind
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=200_000)
    rationale: str | None = Field(default=None, max_length=20_000)
    proof_sketch: ProofStructureRequest | None = None
    attempt: ResearchAttemptRequest | None = None

    @model_validator(mode="after")
    def coherent(self) -> ResearchObjectCreate:
        if not KIND_DEFINITIONS[self.kind].creatable:
            raise ValueError("new proof approaches must use PROOF_SKETCH")
        if (self.kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}) != (
            self.proof_sketch is not None
        ):
            raise ValueError("proof structure is required exactly for proof-sketch records")
        if (self.kind is ResearchObjectKind.ATTEMPT) != (self.attempt is not None):
            raise ValueError("attempt structure is required exactly for attempt records")
        return self


class RevisionCreate(RequestModel):
    base_revision_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=200_000)
    rationale: str | None = Field(default=None, max_length=20_000)
    proof_sketch: ProofStructureRequest | None = None
    attempt: ResearchAttemptRequest | None = None


class RelationCreate(RequestModel):
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str = Field(min_length=1, max_length=20_000)


class CommentCreate(RequestModel):
    revision_id: UUID
    body_md: str = Field(min_length=1, max_length=50_000)


class AuthorRead(ApiModel):
    id: UUID
    display_name: str | None


class ProofStructureRead(ApiModel):
    sketch_revision_id: UUID
    conclusion_revision_id: UUID
    premise_revision_ids: list[UUID]
    reported_progress: ResearchProgressStatus


class AttemptEvidenceRead(ApiModel):
    revision_id: UUID
    role: AttemptEvidenceRole


class ResearchAttemptStructureRead(ApiModel):
    attempt_revision_id: UUID
    target_object_id: UUID
    target_revision_id: UUID
    outcome: ResearchProgressStatus
    findings_md: str
    evidence: list[AttemptEvidenceRead]
    result_revision_id: UUID | None


class VersionContentRead(ApiModel):
    """Complete content shared by exact, embedded, and history projections."""

    semantic_metadata: dict[str, object] = Field(
        default_factory=dict, exclude_if=lambda value: not value
    )
    kind: ResearchObjectKind
    schema_version: int = 1
    rationale: str | None = None
    assumptions_md: str = ""
    reported_outcome: str | None = None
    explanation_md: str | None = None
    statement_revision_ids: list[UUID] = Field(default_factory=list)
    proof_sketch: ProofStructureRead | None = None
    attempt: ResearchAttemptStructureRead | None = None
    catalogue_entry_id: UUID | None = None
    catalogue_source: CatalogueSource | None = None
    catalogue_reported_status: str | None = None
    suggestion: CatalogueRevise | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def structural_relationships(self) -> tuple[VersionRelationship, ...]:
        relationships = [
            VersionRelationship(target_version_id=target, role=StructuralRole.ATTACHMENT)
            for target in self.statement_revision_ids
        ]
        if proof := self.proof_sketch:
            relationships.append(
                VersionRelationship(
                    target_version_id=proof.conclusion_revision_id, role=StructuralRole.CONCLUSION
                )
            )
            relationships.extend(
                VersionRelationship(
                    target_version_id=target, role=StructuralRole.PREMISE, position=position
                )
                for position, target in enumerate(proof.premise_revision_ids)
            )
        if attempt := self.attempt:
            relationships.append(
                VersionRelationship(
                    target_version_id=attempt.target_revision_id, role=StructuralRole.TARGET
                )
            )
            relationships.extend(
                VersionRelationship(
                    target_version_id=item.revision_id,
                    role=StructuralRole.EVIDENCE,
                    position=position,
                    evidence_role=item.role,
                )
                for position, item in enumerate(attempt.evidence)
            )
            if attempt.result_revision_id is not None:
                relationships.append(
                    VersionRelationship(
                        target_version_id=attempt.result_revision_id, role=StructuralRole.RESULT
                    )
                )
        return tuple(relationships)


class RevisionRead(VersionContentRead):
    id: UUID
    object_id: UUID
    number: int
    title: str
    content_md: str
    rationale: str | None
    base_revision_id: UUID | None
    author: AuthorRead
    provenance_kind: ProvenanceKind
    created_at: datetime


class ResearchObjectRead(ApiModel):
    id: UUID
    project_id: UUID
    kind: ResearchObjectKind
    current_revision_id: UUID
    author: AuthorRead
    provenance_kind: ProvenanceKind
    created_at: datetime
    updated_at: datetime
    current_revision: RevisionRead


class RelationRead(ApiModel):
    id: UUID
    project_id: UUID | None
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str
    author: AuthorRead
    provenance_kind: ProvenanceKind
    created_at: datetime


class CommentRead(ApiModel):
    id: UUID
    object_id: UUID
    revision_id: UUID = Field(serialization_alias="object_version_id")
    body_md: str
    author: AuthorRead
    provenance_kind: ProvenanceKind
    created_at: datetime


class NeighborhoodRead(ApiModel):
    revision_id: UUID
    relations: list[RelationRead]
    nodes: list[NeighborhoodNodeRead]


class NeighborhoodNodeRead(ApiModel):
    """Exact revision identity needed for controlled local graph expansion."""

    revision_id: UUID
    object_id: UUID
    title: str


class PublicAuthorRead(BaseModel):
    """Safe attribution; user IDs and email are never public provenance."""

    display_name: str | None
    username: str | None = None


class PublicAgentProvenanceRead(BaseModel):
    """Publicly safe proof that the entity came from a reviewed agent proposal."""

    agent_generated: Literal[True] = True


class PublicRevisionRead(VersionContentRead):
    id: UUID
    number: int
    title: str
    content_md: str
    rationale: str | None
    base_revision_id: UUID | None
    author: PublicAuthorRead
    provenance: PublicAgentProvenanceRead | None = None
    created_at: datetime


class PublicResearchObjectRead(BaseModel):
    id: UUID
    kind: ResearchObjectKind
    current_revision_id: UUID
    created_at: datetime
    provenance: PublicAgentProvenanceRead | None = None
    current_revision: PublicRevisionRead


class PublicRelationRead(BaseModel):
    id: UUID
    source_revision_id: UUID
    target_revision_id: UUID
    relation_type: RelationType
    rationale: str
    author: PublicAuthorRead
    provenance: PublicAgentProvenanceRead | None = None
    created_at: datetime


class PublicCommentRead(BaseModel):
    id: UUID
    revision_id: UUID = Field(serialization_alias="object_version_id")
    body_md: str
    author: PublicAuthorRead
    provenance: PublicAgentProvenanceRead | None = None
    created_at: datetime


class PublicNeighborhoodRead(BaseModel):
    revision_id: UUID
    relations: list[PublicRelationRead]
    nodes: list[PublicNeighborhoodNodeRead]


class PublicNeighborhoodNodeRead(BaseModel):
    """Safe public revision-to-object identity; no author or project metadata."""

    revision_id: UUID
    object_id: UUID
    title: str


__all__ = [
    "ProofStructureRequest",
    "AttemptEvidenceRequest",
    "ResearchAttemptRequest",
    "ResearchObjectCreate",
    "RevisionCreate",
    "RelationCreate",
    "CommentCreate",
    "AuthorRead",
    "RevisionRead",
    "ResearchObjectRead",
    "RelationRead",
    "CommentRead",
    "NeighborhoodRead",
    "NeighborhoodNodeRead",
    "PublicAuthorRead",
    "PublicAgentProvenanceRead",
    "PublicRevisionRead",
    "PublicResearchObjectRead",
    "PublicRelationRead",
    "PublicCommentRead",
    "PublicNeighborhoodRead",
    "PublicNeighborhoodNodeRead",
]

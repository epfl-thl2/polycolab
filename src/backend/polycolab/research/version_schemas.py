"""Object-version wire contracts, separate from historical revision decoders.

Response values must be assembled by an authorized projection. Validating a raw
application snapshot against these schemas does not make it safe for public use.
"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, RootModel, model_validator

from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.catalogue.schemas import CatalogueFormulation, CatalogueSource
from polycolab.entities.enums import (
    AttemptEvidenceRole,
    ContributionActorKind,
    RelationType,
    ResearchProgressStatus,
)
from polycolab.entities.object_kinds import ObjectKind, ProofDirection, StatementLabel
from polycolab.entities.research import StructuralRole


class VersionAuthorshipRead(ApiModel):
    contribution_id: UUID | None
    actor_kind: ContributionActorKind
    author_display_name: str | None
    author_user_id: UUID | None
    agent_id: UUID | None
    sponsor_user_id: UUID | None
    agent_display_name: str | None


DirectedDeclarationType = Literal[
    RelationType.DEPENDS_ON,
    RelationType.PROVES,
    RelationType.ATTEMPTS,
    RelationType.REFUTES,
    RelationType.USES,
    RelationType.IMPLIES,
]


class RelationshipReadBase(ApiModel):
    id: UUID
    relationship_type: StructuralRole | RelationType
    binding: Literal["STRUCTURAL", "DECLARATION"]
    ownership_scope_id: UUID | None
    authorship: VersionAuthorshipRead
    created_at: datetime
    description: str | None


class UnidirectionalRelationshipRead(RelationshipReadBase):
    direction: Literal["UNIDIRECTIONAL"] = "UNIDIRECTIONAL"
    relationship_type: StructuralRole | DirectedDeclarationType
    source_object_version_id: UUID
    target_object_version_id: UUID
    position: int | None
    evidence_role: AttemptEvidenceRole | None


class BidirectionalRelationshipRead(RelationshipReadBase):
    direction: Literal["BIDIRECTIONAL"] = "BIDIRECTIONAL"
    relationship_type: Literal[RelationType.EQUIVALENT_TO]
    binding: Literal["DECLARATION"] = "DECLARATION"
    first_object_version_id: UUID
    second_object_version_id: UUID


ObjectVersionRelationshipRead = Annotated[
    UnidirectionalRelationshipRead | BidirectionalRelationshipRead,
    Field(discriminator="direction"),
]


class VersionContent(RequestModel):
    attached_object_ids: list[UUID] = Field(default_factory=list, max_length=64)
    source_language: Literal["LEAN", "PYTHON"] | None = None
    statement_label: StatementLabel | None = None
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(min_length=1, max_length=100_000)
    assumptions_md: str = Field(min_length=1, max_length=20_000)
    reported_outcome: Literal["UNASSESSED", "IN_PROGRESS", "FAILED", "PARTIAL", "SUCCEEDED"] | None
    explanation_md: str | None = Field(max_length=20_000)


class ProofVersionContent(VersionContent):
    direction: ProofDirection = ProofDirection.SUPPORTS
    reported_progress: ResearchProgressStatus | None


class AttemptVersionContent(VersionContent):
    outcome: ResearchProgressStatus | None
    findings_md: str | None = Field(max_length=50_000)


class VersionContentRead(ApiModel):
    attached_object_ids: list[UUID] = Field(
        default_factory=list, exclude_if=lambda value: not value
    )
    source_language: Literal["LEAN", "PYTHON"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    statement_label: StatementLabel | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    """Historical content is not revalidated against current write limits."""

    title: str
    content_md: str
    assumptions_md: str
    reported_outcome: str | None
    explanation_md: str | None


class ProofVersionContentRead(VersionContentRead):
    direction: ProofDirection | None = None
    reported_progress: ResearchProgressStatus | None


class AttemptVersionContentRead(VersionContentRead):
    outcome: ResearchProgressStatus | None
    findings_md: str | None


OrdinaryKind = Literal["PROBLEM", "DEFINITION", "STATEMENT", "NOTE", "FORMALIZATION"]


class VersionCorrectionSuggestion(CatalogueFormulation):
    expected_current_object_version_id: UUID


class VersionCatalogueMetadata(ApiModel):
    entry_id: UUID | None
    source: CatalogueSource | None
    reported_status: str | None
    suggestion: VersionCorrectionSuggestion | None


class ObjectVersionReadBase(ApiModel):
    legacy_kind: str | None = None
    id: UUID
    object_id: UUID
    number: int = Field(ge=1)
    previous_object_version_id: UUID | None
    schema_version: int = Field(ge=1)
    change_summary: str | None
    authorship: VersionAuthorshipRead
    created_at: datetime
    structural_relationships: list[UnidirectionalRelationshipRead]
    catalogue: VersionCatalogueMetadata | None = None


class OrdinaryObjectVersionRead(ObjectVersionReadBase):
    kind: OrdinaryKind
    content: VersionContentRead


class ProofObjectVersionRead(ObjectVersionReadBase):
    kind: Literal["PROOF"]
    content: ProofVersionContentRead


class AttemptObjectVersionRead(ObjectVersionReadBase):
    kind: Literal["ATTEMPT"]
    content: AttemptVersionContentRead
    legacy_unstructured: bool


ObjectVersionRead = Annotated[
    OrdinaryObjectVersionRead | ProofObjectVersionRead | AttemptObjectVersionRead,
    Field(discriminator="kind"),
]


class ObjectVersionPage(ApiModel):
    items: list[ObjectVersionRead]
    next_cursor: str | None


class VersionDiscoveryHit(ApiModel):
    object_version: ObjectVersionRead
    catalogue_entry_id: UUID | None
    source_identifier: str | None
    source_version: str | None
    source_locator: str | None
    catalogue_status: str | None


class VersionDiscoveryPage(ApiModel):
    items: list[VersionDiscoveryHit]
    next_cursor: str | None


class PublicVersionedObjectRead(ApiModel):
    id: UUID
    kind: ObjectKind
    created_at: datetime
    current_object_version_id: UUID
    current_object_version: ObjectVersionRead


class MemberVersionedObjectRead(PublicVersionedObjectRead):
    ownership_scope_id: UUID
    authorship: VersionAuthorshipRead


VersionedObjectRead = MemberVersionedObjectRead | PublicVersionedObjectRead


class VersionNeighborhoodNodeRead(ApiModel):
    object_version_id: UUID
    object_id: UUID
    title: str


class VersionNeighborhoodRead(ApiModel):
    object_version_id: UUID
    relationships: list[ObjectVersionRelationshipRead]
    nodes: list[VersionNeighborhoodNodeRead]


class StructuralRelationshipInput(RequestModel):
    relationship_type: StructuralRole
    target_object_version_id: UUID
    position: int | None = Field(default=None, ge=0)
    evidence_role: AttemptEvidenceRole | None = None

    @model_validator(mode="after")
    def coherent(self) -> StructuralRelationshipInput:
        ordered = self.relationship_type in {StructuralRole.PREMISE, StructuralRole.EVIDENCE}
        if ordered != (self.position is not None):
            raise ValueError("only premises and evidence require a position")
        if (self.relationship_type == StructuralRole.EVIDENCE) != (self.evidence_role is not None):
            raise ValueError("only evidence requires an evidence role")
        return self


class VersionSnapshotInput(RequestModel):
    kind: str
    content: VersionContent
    structural_relationships: list[StructuralRelationshipInput] = Field(max_length=200)
    change_summary: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def unique_relationships(self) -> VersionSnapshotInput:
        pins = [
            (r.relationship_type, r.target_object_version_id) for r in self.structural_relationships
        ]
        positions = [
            (r.relationship_type, r.position)
            for r in self.structural_relationships
            if r.position is not None
        ]
        if len(set(pins)) != len(pins) or len(set(positions)) != len(positions):
            raise ValueError("duplicate structural targets or positions")
        for role in (StructuralRole.CONCLUSION, StructuralRole.TARGET, StructuralRole.RESULT):
            if sum(r.relationship_type == role for r in self.structural_relationships) > 1:
                raise ValueError("structural role requires a single target")
        targets: dict[StructuralRole, set[UUID]] = {}
        for relationship in self.structural_relationships:
            targets.setdefault(relationship.relationship_type, set()).add(
                relationship.target_object_version_id
            )
        if self.kind != "STATEMENT" and self.content.statement_label is not None:
            raise ValueError("statement labels belong only to statements")
        if self.content.attached_object_ids and self.kind not in {
            "NOTE",
            "ATTEMPT",
        }:
            raise ValueError("object attachments belong only to notes and attempts")
        if len(set(self.content.attached_object_ids)) != len(self.content.attached_object_ids):
            raise ValueError("duplicate object attachments")
        allowed = {StructuralRole.ATTACHMENT}
        if self.kind == "PROOF":
            allowed.update((StructuralRole.CONCLUSION, StructuralRole.PREMISE))
            conclusions = targets.get(StructuralRole.CONCLUSION, set())
            premises = targets.get(StructuralRole.PREMISE, set())
            if len(conclusions) != 1 or conclusions & premises:
                raise ValueError("proof requires one conclusion distinct from its premises")
            if not (conclusions | premises) <= targets.get(StructuralRole.ATTACHMENT, set()):
                raise ValueError("proof pins must also be statement attachments")
            if (
                not isinstance(self.content, ProofVersionContent)
                or self.content.reported_progress is None
            ):
                raise ValueError("proof progress is required")
        if self.kind == "ATTEMPT":
            allowed.update((StructuralRole.TARGET, StructuralRole.EVIDENCE, StructuralRole.RESULT))
            target = targets.get(StructuralRole.TARGET, set())
            if len(target) != 1 or target & targets.get(StructuralRole.RESULT, set()):
                raise ValueError("attempt requires one target and a distinct result")
            if (
                not isinstance(self.content, AttemptVersionContent)
                or self.content.outcome is None
                or not (self.content.findings_md or "").strip()
            ):
                raise ValueError("attempt outcome and findings are required")
        if set(targets) - allowed:
            raise ValueError("structural role does not match object kind")
        return self


class OrdinaryVersionSnapshot(VersionSnapshotInput):
    kind: OrdinaryKind
    content: VersionContent


class ProofVersionSnapshot(VersionSnapshotInput):
    kind: Literal["PROOF"]
    content: ProofVersionContent


class AttemptVersionSnapshot(VersionSnapshotInput):
    kind: Literal["ATTEMPT"]
    content: AttemptVersionContent


EditableVersionSnapshot = Annotated[
    OrdinaryVersionSnapshot | ProofVersionSnapshot | AttemptVersionSnapshot,
    Field(discriminator="kind"),
]


class ObjectVersionCreate(RequestModel):
    expected_current_object_version_id: UUID
    snapshot: EditableVersionSnapshot


class ObjectVersionCommentCreate(RequestModel):
    object_version_id: UUID
    body_md: str = Field(min_length=1, max_length=50_000)


class AgentObjectVersionComment(ObjectVersionCommentCreate):
    object_id: UUID
    project_id: UUID | None = None


class VersionWorkspaceDestination(RequestModel):
    kind: Literal["workspace"]
    workspace_id: UUID


class VersionLibraryDestination(RequestModel):
    kind: Literal["library"]
    statement_object_version_id: UUID


VersionDestination = Annotated[
    VersionWorkspaceDestination | VersionLibraryDestination, Field(discriminator="kind")
]


class VersionedObjectCreate(RequestModel):
    destination: VersionDestination
    snapshot: EditableVersionSnapshot
    catalogue_suggestion: VersionCorrectionSuggestion | None = None

    @model_validator(mode="after")
    def correction_destination(self) -> VersionedObjectCreate:
        if self.catalogue_suggestion is not None:
            target = self.catalogue_suggestion.expected_current_object_version_id
            if (
                not isinstance(self.destination, VersionLibraryDestination)
                or self.destination.statement_object_version_id != target
                or self.snapshot.kind != "NOTE"
                or not any(
                    pin.relationship_type == StructuralRole.ATTACHMENT
                    and pin.target_object_version_id == target
                    for pin in self.snapshot.structural_relationships
                )
            ):
                raise ValueError(
                    "public corrections must be notes attached to their Library destination"
                )
        return self


class UnidirectionalRelationshipInput(RequestModel):
    direction: Literal["UNIDIRECTIONAL"]
    relationship_type: DirectedDeclarationType
    source_object_version_id: UUID
    target_object_version_id: UUID
    description: str | None = Field(default=None, max_length=20_000)


class BidirectionalRelationshipInput(RequestModel):
    direction: Literal["BIDIRECTIONAL"]
    relationship_type: Literal[RelationType.EQUIVALENT_TO]
    first_object_version_id: UUID
    second_object_version_id: UUID
    description: str | None = Field(default=None, max_length=20_000)

    @model_validator(mode="after")
    def canonical_endpoints(self) -> BidirectionalRelationshipInput:
        self.first_object_version_id, self.second_object_version_id = sorted(
            (self.first_object_version_id, self.second_object_version_id)
        )
        return self


ObjectVersionRelationshipInput = Annotated[
    UnidirectionalRelationshipInput | BidirectionalRelationshipInput,
    Field(discriminator="direction"),
]


class UnidirectionalDeclarationCreate(UnidirectionalRelationshipInput):
    destination: VersionDestination


class BidirectionalDeclarationCreate(BidirectionalRelationshipInput):
    destination: VersionDestination


ObjectVersionDeclarationCreate = Annotated[
    UnidirectionalDeclarationCreate | BidirectionalDeclarationCreate,
    Field(discriminator="direction"),
]


class AgentObjectVersionWrite(RequestModel):
    destination: VersionDestination
    object_id: UUID | None = None
    expected_current_object_version_id: UUID | None = None
    snapshot: EditableVersionSnapshot

    @model_validator(mode="after")
    def exact_edit(self) -> AgentObjectVersionWrite:
        if (self.object_id is None) != (self.expected_current_object_version_id is None):
            raise ValueError("editing requires an object and expected current object version")
        return self


class AgentRelationshipWrite(RootModel[ObjectVersionDeclarationCreate]):
    pass

"""Immutable research snapshots. Loading and mutation belong to research services."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from polycolab.entities.enums import (
    AttemptEvidenceRole,
    ContributionActorKind,
    RelationType,
    ResearchEntityClass,
    ResearchObjectKind,
    ResearchProgressStatus,
)


class StructuralRole(StrEnum):
    ATTACHMENT = "ATTACHMENT"
    CONCLUSION = "CONCLUSION"
    PREMISE = "PREMISE"
    TARGET = "TARGET"
    EVIDENCE = "EVIDENCE"
    RESULT = "RESULT"


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchAttribution:
    contribution_id: UUID
    actor_kind: ContributionActorKind
    author_display_name: str | None
    author_user_id: UUID | None = None
    agent_id: UUID | None = None
    sponsor_user_id: UUID | None = None
    agent_display_name: str | None = None
    author_username: str | None = None
    sponsor_username: str | None = None


class RelationshipBinding(StrEnum):
    STRUCTURAL = "STRUCTURAL"
    DECLARATION = "DECLARATION"


class RelationshipDirection(StrEnum):
    UNIDIRECTIONAL = "UNIDIRECTIONAL"
    BIDIRECTIONAL = "BIDIRECTIONAL"


@dataclass(frozen=True, slots=True, kw_only=True)
class ObjectVersionRelationship:
    """An attributed relationship between exact versions, not object heads."""

    id: UUID
    relationship_type: StructuralRole | RelationType
    binding: RelationshipBinding
    ownership_scope_id: UUID
    authorship: ResearchAttribution
    created_at: datetime
    description: str | None = None

    def __post_init__(self) -> None:
        if type(self) is ObjectVersionRelationship:
            raise ValueError("a relationship requires directed or bidirectional endpoints")
        if not isinstance(self.binding, RelationshipBinding):
            raise ValueError("invalid relationship binding")
        if not isinstance(self.relationship_type, (StructuralRole, RelationType)):
            raise ValueError("invalid relationship type")
        if (self.binding is RelationshipBinding.STRUCTURAL) != isinstance(
            self.relationship_type, StructuralRole
        ):
            raise ValueError("relationship type does not match its binding")


@dataclass(frozen=True, slots=True, kw_only=True)
class UnidirectionalRelationship(ObjectVersionRelationship):
    source_object_version_id: UUID
    target_object_version_id: UUID
    position: int | None = None
    evidence_role: AttemptEvidenceRole | None = None

    def __post_init__(self) -> None:
        ObjectVersionRelationship.__post_init__(self)
        if self.relationship_type is RelationType.EQUIVALENT_TO:
            raise ValueError("equivalence requires bidirectional endpoints")
        ordered = self.relationship_type in {StructuralRole.PREMISE, StructuralRole.EVIDENCE}
        if ordered != (self.position is not None):
            raise ValueError("only premises and evidence require a position")
        if self.position is not None and self.position < 0:
            raise ValueError("relationship position must be nonnegative")
        if (self.relationship_type is StructuralRole.EVIDENCE) != (self.evidence_role is not None):
            raise ValueError("only evidence relationships require an evidence role")

    @property
    def direction(self) -> RelationshipDirection:
        return RelationshipDirection.UNIDIRECTIONAL


@dataclass(frozen=True, slots=True, kw_only=True)
class BidirectionalRelationship(ObjectVersionRelationship):
    first_object_version_id: UUID
    second_object_version_id: UUID

    def __post_init__(self) -> None:
        ObjectVersionRelationship.__post_init__(self)
        if self.relationship_type is not RelationType.EQUIVALENT_TO:
            raise ValueError("relationship type does not support bidirectional endpoints")
        first, second = sorted((self.first_object_version_id, self.second_object_version_id))
        object.__setattr__(self, "first_object_version_id", first)
        object.__setattr__(self, "second_object_version_id", second)

    @property
    def direction(self) -> RelationshipDirection:
        return RelationshipDirection.BIDIRECTIONAL


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptEvidence:
    object_version_id: UUID
    role: AttemptEvidenceRole


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchContent:
    """A complete immutable content snapshot, never an incremental patch."""

    title: str
    content_md: str
    assumptions_md: str
    reported_outcome: str | None
    explanation_md: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofSketchContent(ResearchContent):
    reported_progress: ResearchProgressStatus | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptContent(ResearchContent):
    outcome: ResearchProgressStatus | None = None
    findings_md: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchObjectVersion:
    id: UUID
    object_id: UUID
    kind: ResearchObjectKind
    number: int
    previous_object_version_id: UUID | None
    schema_version: int
    content: ResearchContent
    change_summary: str | None
    authorship: ResearchAttribution
    created_at: datetime
    structural_relationships: tuple[UnidirectionalRelationship, ...] = ()

    def __post_init__(self) -> None:
        if self.number < 1 or self.schema_version < 1:
            raise ValueError("version numbers must be positive")
        if self.previous_object_version_id == self.id:
            raise ValueError("a version cannot be its own predecessor")
        if (self.number == 1) != (self.previous_object_version_id is None):
            raise ValueError("only the first version has no predecessor")
        if type(self) is not KIND_DEFINITIONS[self.kind].version_type:
            raise ValueError("version type does not match research kind")
        if type(self.content) is not KIND_DEFINITIONS[self.kind].content_type:
            raise ValueError("content type does not match research kind")
        relationships = tuple(self.structural_relationships)
        object.__setattr__(self, "structural_relationships", relationships)
        seen: set[tuple[StructuralRole | RelationType, UUID]] = set()
        positions: dict[StructuralRole | RelationType, list[int]] = {}
        for relationship in relationships:
            if relationship.binding is not RelationshipBinding.STRUCTURAL:
                raise ValueError("version snapshots contain only structural relationships")
            if relationship.source_object_version_id != self.id:
                raise ValueError("structural source must be this exact version")
            if (
                relationship.authorship != self.authorship
                or relationship.created_at != self.created_at
            ):
                raise ValueError("structural authorship must match its version")
            key = (relationship.relationship_type, relationship.target_object_version_id)
            if key in seen:
                raise ValueError("duplicate structural relationship")
            seen.add(key)
            if relationship.position is not None:
                positions.setdefault(relationship.relationship_type, []).append(
                    relationship.position
                )
        for ordered in positions.values():
            if len(set(ordered)) != len(ordered):
                raise ValueError("structural positions must be unique")
        for role in (StructuralRole.CONCLUSION, StructuralRole.TARGET, StructuralRole.RESULT):
            if len(self._targets(role)) > 1:
                raise ValueError("structural role requires a single target")
        allowed = {StructuralRole.ATTACHMENT}
        if self.kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}:
            allowed.update((StructuralRole.CONCLUSION, StructuralRole.PREMISE))
        if self.kind is ResearchObjectKind.ATTEMPT:
            allowed.update((StructuralRole.TARGET, StructuralRole.EVIDENCE, StructuralRole.RESULT))
        if any(item.relationship_type not in allowed for item in relationships):
            raise ValueError("structural role does not match research kind")

    def _targets(self, role: StructuralRole) -> tuple[UUID, ...]:
        return tuple(
            item.target_object_version_id
            for item in sorted(
                self.structural_relationships,
                key=lambda r: (
                    r.position if r.position is not None else -1,
                    r.target_object_version_id,
                ),
            )
            if item.relationship_type is role
        )

    @property
    def statement_object_version_ids(self) -> tuple[UUID, ...]:
        return self._targets(StructuralRole.ATTACHMENT)


@dataclass(frozen=True, slots=True, kw_only=True)
class StatementVersion(ResearchObjectVersion):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordVersion(ResearchObjectVersion):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofSketchVersion(RecordVersion):
    content: ProofSketchContent
    # Historical PROOF rows can predate structured proofs. Missing content is
    # retained as unknown; new PROOF_SKETCH versions always require structure.

    def __post_init__(self) -> None:
        RecordVersion.__post_init__(self)
        if self.conclusion_object_version_id is None:
            if (
                self.kind is not ResearchObjectKind.PROOF
                or self.premise_object_version_ids
                or self.content.reported_progress is not None
            ):
                raise ValueError("proof-sketch structure is required")
            return
        if self.content.reported_progress is None:
            raise ValueError("structured proofs require reported progress")
        if len(set(self.premise_object_version_ids)) != len(self.premise_object_version_ids):
            raise ValueError("duplicate proof premises")
        if self.conclusion_object_version_id in self.premise_object_version_ids:
            raise ValueError("a conclusion cannot be its own premise")
        if not {self.conclusion_object_version_id, *self.premise_object_version_ids}.issubset(
            self.statement_object_version_ids
        ):
            raise ValueError("proof dependencies must be statement attachments")

    @property
    def conclusion_object_version_id(self) -> UUID | None:
        return next(iter(self._targets(StructuralRole.CONCLUSION)), None)

    @property
    def premise_object_version_ids(self) -> tuple[UUID, ...]:
        return self._targets(StructuralRole.PREMISE)


@dataclass(frozen=True, slots=True, kw_only=True)
class AttemptVersion(RecordVersion):
    content: AttemptContent
    target_object_id: UUID | None = None
    legacy_unstructured: bool = False

    def __post_init__(self) -> None:
        RecordVersion.__post_init__(self)
        if self.legacy_unstructured:
            if any(
                (
                    self.target_object_id,
                    self.target_object_version_id,
                    self.content.outcome,
                    self.content.findings_md,
                    self.evidence,
                    self.result_object_version_id,
                )
            ):
                raise ValueError("legacy attempt cannot contain partial invented structure")
            return
        if (
            self.target_object_id is None
            or self.target_object_version_id is None
            or self.content.outcome is None
            or self.content.findings_md is None
        ):
            raise ValueError("attempt structure is required")
        if len({item.object_version_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("duplicate attempt evidence")
        if self.result_object_version_id == self.target_object_version_id:
            raise ValueError("attempt result must differ from target")

    @property
    def target_object_version_id(self) -> UUID | None:
        return next(iter(self._targets(StructuralRole.TARGET)), None)

    @property
    def result_object_version_id(self) -> UUID | None:
        return next(iter(self._targets(StructuralRole.RESULT)), None)

    @property
    def evidence(self) -> tuple[AttemptEvidence, ...]:
        return tuple(
            AttemptEvidence(
                object_version_id=item.target_object_version_id, role=item.evidence_role
            )
            for item in sorted(self.structural_relationships, key=lambda r: r.position or 0)
            if item.relationship_type is StructuralRole.EVIDENCE and item.evidence_role is not None
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchObject:
    id: UUID
    ownership_scope_id: UUID
    kind: ResearchObjectKind
    authorship: ResearchAttribution
    created_at: datetime
    current_object_version_id: UUID

    def __post_init__(self) -> None:
        if type(self) is not KIND_DEFINITIONS[self.kind].object_type:
            raise ValueError("object type does not match research kind")


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchStatement(ResearchObject):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchRecord(ResearchObject):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofSketch(ResearchObject):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchAttempt(ResearchObject):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchObjectRead:
    """An explicitly selected, authorized version alongside its stable identity.

    The selected version need not be the actual head (for example, public reads).
    This internal value is not an anonymously serializable projection.
    """

    object: ResearchObject
    version: ResearchObjectVersion

    def __post_init__(self) -> None:
        if self.version.object_id != self.object.id or self.version.kind != self.object.kind:
            raise ValueError("selected version must belong to the object and kind")


@dataclass(frozen=True, slots=True)
class KindDefinition:
    entity_class: ResearchEntityClass
    object_type: type[ResearchStatement | ResearchRecord | ProofSketch | ResearchAttempt]
    version_type: type[ResearchObjectVersion]
    content_type: type[ResearchContent] = ResearchContent
    creatable: bool = True


KIND_DEFINITIONS = MappingProxyType(
    {
        **{
            kind: KindDefinition(ResearchEntityClass.STATEMENT, ResearchStatement, StatementVersion)
            for kind in (
                ResearchObjectKind.PROBLEM,
                ResearchObjectKind.DEFINITION,
                ResearchObjectKind.CLAIM,
            )
        },
        **{
            kind: KindDefinition(ResearchEntityClass.RECORD, ResearchRecord, RecordVersion)
            for kind in (
                ResearchObjectKind.NOTE,
                ResearchObjectKind.IDEA,
                ResearchObjectKind.DISCUSSION,
                ResearchObjectKind.COUNTEREXAMPLE,
                ResearchObjectKind.FORMALIZATION,
                ResearchObjectKind.COMPUTATION,
            )
        },
        ResearchObjectKind.PROOF_SKETCH: KindDefinition(
            ResearchEntityClass.RECORD, ProofSketch, ProofSketchVersion, ProofSketchContent
        ),
        ResearchObjectKind.PROOF: KindDefinition(
            ResearchEntityClass.RECORD,
            ProofSketch,
            ProofSketchVersion,
            ProofSketchContent,
            creatable=False,
        ),
        ResearchObjectKind.ATTEMPT: KindDefinition(
            ResearchEntityClass.RECORD, ResearchAttempt, AttemptVersion, AttemptContent
        ),
    }
)

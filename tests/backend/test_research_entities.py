from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from polycolab.entities.enums import (
    AttemptEvidenceRole,
    ContributionActorKind,
    RelationType,
    ResearchObjectKind,
    ResearchProgressStatus,
)
from polycolab.entities.research import (
    KIND_DEFINITIONS,
    AttemptVersion,
    BidirectionalRelationship,
    ProofSketch,
    ProofSketchVersion,
    RelationshipBinding,
    ResearchAttribution,
    ResearchObjectRead,
    StatementVersion,
    StructuralRole,
    UnidirectionalRelationship,
)


def common(
    kind: ResearchObjectKind = ResearchObjectKind.CLAIM, **content_values: Any
) -> dict[str, Any]:
    return dict(
        id=uuid4(),
        object_id=uuid4(),
        kind=kind,
        number=1,
        previous_object_version_id=None,
        schema_version=1,
        content=KIND_DEFINITIONS[kind].content_type(
            title="Claim",
            content_md="A complete snapshot",
            assumptions_md="None",
            reported_outcome=None,
            explanation_md=None,
            **content_values,
        ),
        change_summary=None,
        authorship=ResearchAttribution(
            contribution_id=uuid4(),
            actor_kind=ContributionActorKind.HUMAN,
            author_display_name="Author",
        ),
        created_at=datetime.now(UTC),
    )


def link(
    values: dict[str, Any],
    role: StructuralRole,
    target: Any,
    position: int | None = None,
    evidence_role: AttemptEvidenceRole | None = None,
) -> UnidirectionalRelationship:
    return UnidirectionalRelationship(
        id=uuid4(),
        relationship_type=role,
        binding=RelationshipBinding.STRUCTURAL,
        ownership_scope_id=uuid4(),
        authorship=values["authorship"],
        created_at=values["created_at"],
        source_object_version_id=values["id"],
        target_object_version_id=target,
        position=position,
        evidence_role=evidence_role,
    )


@pytest.mark.parametrize("kind", list(ResearchObjectKind))
def test_every_kind_has_a_coherent_object_and_version(kind: ResearchObjectKind) -> None:
    values = common(kind)
    conclusion, premise = uuid4(), uuid4()
    relationships = [
        link(values, StructuralRole.ATTACHMENT, target) for target in (conclusion, premise)
    ]
    if kind in {ResearchObjectKind.PROOF, ResearchObjectKind.PROOF_SKETCH}:
        values["content"] = replace(
            values["content"], reported_progress=ResearchProgressStatus.POTENTIAL
        )
        relationships.extend(
            (
                link(values, StructuralRole.CONCLUSION, conclusion),
                link(values, StructuralRole.PREMISE, premise, 0),
            )
        )
    if kind is ResearchObjectKind.ATTEMPT:
        values["content"] = replace(
            values["content"], outcome=ResearchProgressStatus.POTENTIAL, findings_md="Exploring"
        )
        values["target_object_id"] = uuid4()
        relationships.append(link(values, StructuralRole.TARGET, conclusion))
    definition = KIND_DEFINITIONS[kind]
    version = definition.version_type(**values, structural_relationships=tuple(relationships))
    obj = definition.object_type(
        id=version.object_id,
        ownership_scope_id=uuid4(),
        kind=kind,
        authorship=version.authorship,
        created_at=version.created_at,
        current_object_version_id=version.id,
    )
    assert ResearchObjectRead(object=obj, version=version).version is version
    assert obj.current_object_version_id == version.id
    assert not hasattr(obj, "current_version")
    assert definition.creatable == (kind is not ResearchObjectKind.PROOF)


def test_proof_dependencies_keep_roles_order_and_old_snapshot() -> None:
    conclusion, first, second = uuid4(), uuid4(), uuid4()
    values = common(
        ResearchObjectKind.PROOF_SKETCH, reported_progress=ResearchProgressStatus.POTENTIAL
    )
    version = ProofSketchVersion(
        **values,
        structural_relationships=(
            *(
                link(values, StructuralRole.ATTACHMENT, target)
                for target in (conclusion, first, second)
            ),
            link(values, StructuralRole.CONCLUSION, conclusion),
            link(values, StructuralRole.PREMISE, second, 0),
            link(values, StructuralRole.PREMISE, first, 1),
        ),
    )
    new_id = uuid4()
    updated = replace(
        version,
        id=new_id,
        number=2,
        previous_object_version_id=version.id,
        structural_relationships=tuple(
            replace(
                r,
                id=uuid4(),
                source_object_version_id=new_id,
                position=0 if r.relationship_type is StructuralRole.PREMISE else r.position,
            )
            for r in version.structural_relationships
            if not (
                r.relationship_type is StructuralRole.PREMISE
                and r.target_object_version_id == second
            )
        ),
    )
    assert version.premise_object_version_ids == (second, first)
    assert updated.premise_object_version_ids == (first,)
    assert sum(r.target_object_version_id == first for r in version.structural_relationships) == 2
    with pytest.raises(FrozenInstanceError):
        version.content.content_md = "rewritten"  # type: ignore[misc]
    with pytest.raises(ValueError, match="belong"):
        ResearchObjectRead(
            object=ProofSketch(
                id=uuid4(),
                ownership_scope_id=uuid4(),
                kind=version.kind,
                authorship=version.authorship,
                created_at=version.created_at,
                current_object_version_id=version.id,
            ),
            version=version,
        )


def test_attempt_evidence_role_is_preserved() -> None:
    values = common(
        ResearchObjectKind.ATTEMPT,
        outcome=ResearchProgressStatus.FAILED,
        findings_md="Counterexample",
    )
    evidence = link(values, StructuralRole.EVIDENCE, uuid4(), 0, AttemptEvidenceRole.CONTRADICTS)
    version = AttemptVersion(
        **values,
        target_object_id=uuid4(),
        structural_relationships=(link(values, StructuralRole.TARGET, uuid4()), evidence),
    )
    assert version.evidence[0].object_version_id == evidence.target_object_version_id
    assert version.evidence[0].role is AttemptEvidenceRole.CONTRADICTS
    assert evidence.position == 0


def test_wrong_version_kind_and_self_predecessor_are_rejected() -> None:
    with pytest.raises(ValueError, match="type"):
        StatementVersion(**common(ResearchObjectKind.NOTE))
    values = common()
    values["previous_object_version_id"] = values["id"]
    with pytest.raises(ValueError, match="own predecessor"):
        StatementVersion(**values)


def test_historical_proof_without_structure_is_not_fabricated() -> None:
    historical = ProofSketchVersion(**common(ResearchObjectKind.PROOF))
    assert historical.conclusion_object_version_id is None
    assert historical.content.reported_progress is None
    assert historical.structural_relationships == ()
    with pytest.raises(ValueError, match="structure is required"):
        ProofSketchVersion(**common(ResearchObjectKind.PROOF_SKETCH))


def test_bidirectional_endpoints_are_canonical_without_ownership() -> None:
    first, second = sorted((uuid4(), uuid4()))
    values = common()
    relation = BidirectionalRelationship(
        id=uuid4(),
        relationship_type=RelationType.EQUIVALENT_TO,
        binding=RelationshipBinding.DECLARATION,
        ownership_scope_id=uuid4(),
        authorship=values["authorship"],
        created_at=values["created_at"],
        first_object_version_id=second,
        second_object_version_id=first,
    )
    assert relation.first_object_version_id == first
    assert relation.second_object_version_id == second
    assert not hasattr(relation, "source_object_version_id")
    with pytest.raises(ValueError, match="bidirectional"):
        replace(relation, relationship_type=RelationType.DEPENDS_ON)


def test_a_version_cannot_embed_late_declarations_or_another_versions_structure() -> None:
    values = common()
    attachment = link(values, StructuralRole.ATTACHMENT, uuid4())
    with pytest.raises(ValueError, match="exact version"):
        StatementVersion(
            **values,
            structural_relationships=(replace(attachment, source_object_version_id=uuid4()),),
        )
    declaration = replace(
        attachment,
        binding=RelationshipBinding.DECLARATION,
        relationship_type=RelationType.DEPENDS_ON,
    )
    with pytest.raises(ValueError, match="only structural"):
        StatementVersion(**values, structural_relationships=(declaration,))

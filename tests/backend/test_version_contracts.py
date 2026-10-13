"""New live contracts must not inherit the permissive historical wire shapes."""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from polycolab.research.direct import OutputRead
from polycolab.research.version_schemas import (
    EditableVersionSnapshot,
    ObjectVersionCreate,
    ObjectVersionDeclarationCreate,
    ObjectVersionRead,
    UnidirectionalRelationshipRead,
)


def test_unidirectional_read_contract_excludes_equivalence() -> None:
    relationship_type = UnidirectionalRelationshipRead.model_fields["relationship_type"]
    adapter: TypeAdapter[Any] = TypeAdapter(relationship_type.annotation)
    assert adapter.validate_python("DEPENDS_ON") == "DEPENDS_ON"
    assert adapter.validate_python("PREMISE") == "PREMISE"
    with pytest.raises(ValidationError):
        adapter.validate_python("EQUIVALENT_TO")


@pytest.mark.parametrize(
    "stored,current",
    [
        ("OBJECT_REVISION", "OBJECT_VERSION"),
        ("RELATION_ASSERTION", "OBJECT_VERSION_RELATIONSHIP"),
        ("SUMMARY_REVISION", "SUMMARY_REVISION"),
    ],
)
def test_receipt_projection_preserves_stored_identity(stored: str, current: str) -> None:
    identifier = uuid4()
    output = OutputRead(entity_type=stored, entity_id=identifier)
    assert output.entity_type == stored
    assert output.model_dump(mode="json") == {"entity_type": current, "entity_id": str(identifier)}


def snapshot() -> dict[str, Any]:
    return {
        "kind": "STATEMENT",
        "content": {
            "title": "Claim",
            "content_md": "Complete content",
            "assumptions_md": "None",
            "reported_outcome": None,
            "explanation_md": None,
        },
        "structural_relationships": [],
    }


def test_version_write_requires_explicit_complete_snapshot() -> None:
    payload: dict[str, Any] = {
        "expected_current_object_version_id": uuid4(),
        "snapshot": snapshot(),
    }
    assert ObjectVersionCreate.model_validate(payload).snapshot.structural_relationships == []
    for field in ("title", "content_md", "assumptions_md", "reported_outcome", "explanation_md"):
        incomplete = snapshot()
        del incomplete["content"][field]
        with pytest.raises(ValidationError):
            ObjectVersionCreate.model_validate({**payload, "snapshot": incomplete})
    del payload["snapshot"]["structural_relationships"]
    with pytest.raises(ValidationError):
        ObjectVersionCreate.model_validate(payload)


@pytest.mark.parametrize(
    "field", ["base_revision_id", "previous_object_version_id", "number", "authorship"]
)
def test_version_write_rejects_old_guard_and_server_owned_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ObjectVersionCreate.model_validate(
            {
                "expected_current_object_version_id": uuid4(),
                "snapshot": snapshot(),
                field: str(uuid4()),
            }
        )


def test_proof_requires_complete_noncontradictory_pins() -> None:
    value = snapshot()
    value["kind"] = "PROOF"
    value["content"]["reported_progress"] = "POTENTIAL"
    adapter: TypeAdapter[EditableVersionSnapshot] = TypeAdapter(EditableVersionSnapshot)
    with pytest.raises(ValidationError, match="conclusion"):
        adapter.validate_python(value)
    target = uuid4()
    value["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": target}
        for role in ("ATTACHMENT", "CONCLUSION")
    ]
    adapter.validate_python(value)
    value["structural_relationships"].append(
        {
            "relationship_type": "PREMISE",
            "target_object_version_id": target,
            "position": 7,
        }
    )
    with pytest.raises(ValidationError, match="distinct"):
        adapter.validate_python(value)


def test_ordinary_kind_cannot_include_attempt_structure() -> None:
    value = snapshot()
    value["structural_relationships"] = [
        {"relationship_type": "TARGET", "target_object_version_id": uuid4()}
    ]
    with pytest.raises(ValidationError, match="kind"):
        TypeAdapter(EditableVersionSnapshot).validate_python(value)


def test_version_schema_has_kind_discriminator_and_no_revision_fields() -> None:
    schema = TypeAdapter(ObjectVersionRead).json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert set(schema["discriminator"]["mapping"]) == {
        "PROBLEM",
        "STATEMENT",
        "PROOF",
        "DEFINITION",
        "NOTE",
        "FORMALIZATION",
        "ATTEMPT",
    }
    assert "base_revision_id" not in str(schema)


def test_equivalence_requires_independent_destination_and_symmetric_endpoints() -> None:
    first, second = sorted((uuid4(), uuid4()))
    value = {
        "direction": "BIDIRECTIONAL",
        "relationship_type": "EQUIVALENT_TO",
        "first_object_version_id": second,
        "second_object_version_id": first,
        "destination": {"kind": "project", "project_id": uuid4()},
    }
    adapter: TypeAdapter[ObjectVersionDeclarationCreate] = TypeAdapter(
        ObjectVersionDeclarationCreate
    )
    result = adapter.validate_python(value).model_dump()
    assert result["first_object_version_id"] == first
    assert result["second_object_version_id"] == second
    assert "source_object_version_id" not in result
    with pytest.raises(ValidationError):
        adapter.validate_python({**value, "source_object_version_id": first})
    with pytest.raises(ValidationError):
        adapter.validate_python({k: v for k, v in value.items() if k != "destination"})
    with pytest.raises(ValidationError):
        adapter.validate_python({**value, "relationship_type": "DEPENDS_ON"})


@pytest.mark.parametrize("explanation", [None, ""])
def test_failed_progress_allows_no_explanation(explanation: str | None) -> None:
    content = snapshot()
    content["content"]["reported_outcome"] = "FAILED"
    content["content"]["explanation_md"] = explanation
    result = ObjectVersionCreate.model_validate(
        {"expected_current_object_version_id": uuid4(), "snapshot": content}
    )
    assert result.snapshot.content.reported_outcome == "FAILED"
    assert result.snapshot.content.explanation_md == explanation

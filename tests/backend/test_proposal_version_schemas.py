"""Proposal input foundations share direct-write snapshot and pin invariants."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_version_contracts import snapshot

from polycolab.agents.proposal_version_schemas import (
    ObjectVersionProposalSubmit,
    proposal_change_adapter,
)
from polycolab.agents.proposals import validate_change
from polycolab.agents.tools import (
    PLATFORM_TOOL_DEFINITIONS,
    ToolCapabilityInvalid,
    _validated_tool_arguments,
)


def test_proposal_version_requires_complete_snapshot_and_exact_guard() -> None:
    value: dict[str, Any] = {
        "kind": "CREATE_OBJECT_VERSION",
        "object_id": str(uuid4()),
        "expected_current_object_version_id": str(uuid4()),
        "snapshot": snapshot(),
    }
    parsed = proposal_change_adapter.validate_python(value)
    assert parsed.model_dump(mode="json")["snapshot"]["structural_relationships"] == []
    for field in ("title", "assumptions_md", "reported_outcome", "explanation_md"):
        incomplete = deepcopy(value)
        del incomplete["snapshot"]["content"][field]
        with pytest.raises(ValidationError):
            proposal_change_adapter.validate_python(incomplete)
    for field in ("object_id", "expected_current_object_version_id", "snapshot"):
        with pytest.raises(ValidationError):
            proposal_change_adapter.validate_python({k: v for k, v in value.items() if k != field})
    with pytest.raises(ValidationError):
        proposal_change_adapter.validate_python({**value, "kind": "CREATE_REVISION"})


@pytest.mark.parametrize("field", ["destination", "workspace_id", "authorship", "contribution_id"])
def test_proposal_does_not_accept_caller_owned_authority(field: str) -> None:
    with pytest.raises(ValidationError):
        proposal_change_adapter.validate_python(
            {"kind": "CREATE_OBJECT", "snapshot": snapshot(), field: str(uuid4())}
        )


def test_proposal_proof_and_attempt_share_typed_snapshot_validation() -> None:
    value = snapshot()
    value["kind"] = "PROOF"
    value["content"]["reported_progress"] = "POTENTIAL"
    with pytest.raises(ValidationError, match="conclusion"):
        proposal_change_adapter.validate_python({"kind": "CREATE_OBJECT", "snapshot": value})
    target = str(uuid4())
    value["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": target}
        for role in ("CONCLUSION", "ATTACHMENT")
    ]
    proposal_change_adapter.validate_python({"kind": "CREATE_OBJECT", "snapshot": value})
    value = snapshot()
    value["kind"] = "ATTEMPT"
    value["content"].update(outcome="FAILED", findings_md="The reduction fails")
    value["structural_relationships"] = [
        {"relationship_type": "TARGET", "target_object_version_id": target}
    ]
    proposal_change_adapter.validate_python({"kind": "CREATE_OBJECT", "snapshot": value})


def test_proposal_relationship_is_symmetric_and_cannot_supply_a_destination() -> None:
    first, second = sorted((uuid4(), uuid4()))
    relationship: dict[str, Any] = {
        "direction": "BIDIRECTIONAL",
        "relationship_type": "EQUIVALENT_TO",
        "first_object_version_id": str(second),
        "second_object_version_id": str(first),
    }
    value = {"kind": "CREATE_RELATIONSHIP", "relationship": relationship}
    saved = proposal_change_adapter.validate_python(value).model_dump(mode="json")
    assert saved["relationship"]["first_object_version_id"] == str(first)
    assert saved["relationship"]["second_object_version_id"] == str(second)
    for field in ("source_object_version_id", "destination"):
        with pytest.raises(ValidationError):
            proposal_change_adapter.validate_python(
                {**value, "relationship": {**relationship, field: str(uuid4())}}
            )


def test_comment_version_wire_is_separate_from_historical_decoder() -> None:
    legacy: dict[str, Any] = {
        "kind": "CREATE_COMMENT",
        "object_id": str(uuid4()),
        "revision_id": str(uuid4()),
        "body_md": "Review this pinned source",
    }
    original = deepcopy(legacy)
    assert str(validate_change(legacy).model_dump()["revision_id"]) == legacy["revision_id"]
    with pytest.raises(ValidationError):
        proposal_change_adapter.validate_python(legacy)
    current = {
        **{k: v for k, v in legacy.items() if k != "revision_id"},
        "object_version_id": legacy["revision_id"],
    }
    proposal = ObjectVersionProposalSubmit.model_validate(
        {"summary": "Pinned review", "changes": [current]}
    )
    assert proposal.model_dump(mode="json")["changes"][0] == current
    assert legacy == original
    with pytest.raises(ValidationError):
        ObjectVersionProposalSubmit(summary="Empty", changes=[])


def test_hosted_proposal_tool_advertises_and_enforces_version_snapshots() -> None:
    definition = next(
        item["function"]
        for item in PLATFORM_TOOL_DEFINITIONS
        if isinstance(item["function"], dict) and item["function"]["name"] == "submit_proposal"
    )
    assert isinstance(definition, dict)
    assert definition["parameters"] == ObjectVersionProposalSubmit.model_json_schema()
    _validated_tool_arguments(
        "submit_proposal",
        {
            "summary": "Complete snapshot",
            "changes": [{"kind": "CREATE_OBJECT", "snapshot": snapshot()}],
        },
    )
    with pytest.raises(ToolCapabilityInvalid):
        _validated_tool_arguments(
            "submit_proposal",
            {
                "summary": "Legacy",
                "changes": [
                    {
                        "kind": "CREATE_OBJECT",
                        "object_kind": "CLAIM",
                        "title": "Old",
                        "content_md": "Old",
                    }
                ],
            },
        )
    with pytest.raises(ToolCapabilityInvalid):
        _validated_tool_arguments(
            "submit_proposal",
            {"summary": " ", "changes": [{"kind": "CREATE_OBJECT", "snapshot": snapshot()}]},
        )

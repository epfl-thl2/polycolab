"""Historical proposal projections describe the same intent without mutation."""

from copy import deepcopy
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from test_catalogue_api import enable
from test_proposal_version_application import submit
from test_proposals_api import headers
from test_research_domain import create_workspace
from test_version_api import create_versioned, snapshot

from polycolab.agents.proposal_projections import proposal_payload_read
from polycolab.agents.proposal_version_schemas import ObjectVersionProposalPayloadRead
from polycolab.db.models import SqlProposalChange


def test_historical_edit_projection_matches_applied_content_and_inherited_pins(
    client: TestClient,
) -> None:
    enable(client)
    project = create_workspace(client)
    statement = create_versioned(client, project, snapshot())
    initial = snapshot()
    initial["kind"] = "NOTE"
    initial["content"].pop("statement_label", None)
    initial["content"].update(
        assumptions_md="Preserved assumptions",
        reported_outcome="PARTIAL",
        explanation_md="A case remains",
    )
    initial["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": statement["id"]}
    ]
    source = create_versioned(client, project, initial)
    legacy = {
        "kind": "CREATE_REVISION",
        "object_id": source["object_id"],
        "base_revision_id": source["id"],
        "title": "Revised note",
        "content_md": "Revised content",
        "rationale": "Recorded reason",
    }
    original = deepcopy(legacy)
    with cast(Any, client.app).state.session_factory() as db:
        projected = proposal_payload_read(db, project_id=UUID(project), payload=legacy)
    assert legacy == original
    assert projected["expected_current_object_version_id"] == source["id"]
    assert "base_revision_id" not in projected
    assert projected["snapshot"]["structural_relationships"] == initial["structural_relationships"]
    proposal, changes = submit(client, project, [source["id"], statement["id"]], [legacy])
    with cast(Any, client.app).state.session_factory() as db:
        stored_before = deepcopy(db.get(SqlProposalChange, UUID(changes[0])).payload)
    detail = client.get(f"/api/v1/proposals/{proposal}", headers=headers("owner"))
    assert detail.status_code == 200, detail.text
    assert detail.json()["changes"][0]["change_type"] == "CREATE_OBJECT_VERSION"
    expected: ObjectVersionProposalPayloadRead = TypeAdapter(
        ObjectVersionProposalPayloadRead
    ).validate_python(projected)
    assert detail.json()["changes"][0]["payload"] == expected.model_dump(mode="json")
    with cast(Any, client.app).state.session_factory() as db:
        assert db.get(SqlProposalChange, UUID(changes[0])).payload == stored_before
    response = client.post(
        f"/api/v1/proposals/{proposal}/changes/{changes[0]}/accept",
        headers={**headers("owner"), "Idempotency-Key": "legacy-accept"},
        json={},
    )
    assert response.status_code == 200, response.text
    exact = client.get(
        f"/api/v1/versions/{response.json()['applied_entity_id']}", headers=headers("owner")
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["content"] == projected["snapshot"]["content"]
    assert exact.json()["change_summary"] == projected["snapshot"]["change_summary"]


def test_historical_relationship_and_comment_projection_preserve_identity(
    client: TestClient,
) -> None:
    first, second = sorted((uuid4(), uuid4()))
    legacy: dict[str, object] = {
        "kind": "CREATE_RELATION",
        "source_revision_id": str(second),
        "target_revision_id": str(first),
        "relation_type": "EQUIVALENT_TO",
        "rationale": "Same claim",
    }
    original = deepcopy(legacy)
    with cast(Any, client.app).state.session_factory() as db:
        result = proposal_payload_read(db, project_id=uuid4(), payload=legacy)
        assert result == {
            "kind": "CREATE_RELATIONSHIP",
            "relationship": {
                "direction": "BIDIRECTIONAL",
                "relationship_type": "EQUIVALENT_TO",
                "description": "Same claim",
                "first_object_version_id": str(first),
                "second_object_version_id": str(second),
            },
        }
        comment = proposal_payload_read(
            db,
            project_id=uuid4(),
            payload={
                "kind": "CREATE_COMMENT",
                "object_id": str(first),
                "revision_id": str(second),
                "body_md": "Review",
            },
        )
    assert legacy == original
    assert comment["object_version_id"] == str(second)
    assert "revision_id" not in comment


def test_historical_creation_does_not_invent_assumptions(client: TestClient) -> None:
    with cast(Any, client.app).state.session_factory() as db:
        result = proposal_payload_read(
            db,
            project_id=uuid4(),
            payload={
                "kind": "CREATE_OBJECT",
                "object_kind": "CLAIM",
                "title": "Old claim",
                "content_md": "Old content",
            },
        )
    assert result["snapshot"]["content"]["assumptions_md"] == ""
    assert result["snapshot"]["change_summary"] is None


def test_historical_proof_projection_retains_order_and_attachments(client: TestClient) -> None:
    conclusion, first, second = (str(uuid4()) for _ in range(3))
    with cast(Any, client.app).state.session_factory() as db:
        result = proposal_payload_read(
            db,
            project_id=uuid4(),
            payload={
                "kind": "CREATE_OBJECT",
                "object_kind": "PROOF_SKETCH",
                "title": "Sketch",
                "content_md": "Argument",
                "proof_sketch": {
                    "conclusion_revision_id": conclusion,
                    "premise_revision_ids": [second, first],
                    "reported_progress": "POTENTIAL",
                },
            },
        )
    snapshot_value = result["snapshot"]
    assert snapshot_value["content"]["reported_progress"] == "POTENTIAL"
    pins = snapshot_value["structural_relationships"]
    assert [pin for pin in pins if pin["relationship_type"] == "PREMISE"] == [
        {"relationship_type": "PREMISE", "target_object_version_id": second, "position": 0},
        {"relationship_type": "PREMISE", "target_object_version_id": first, "position": 1},
    ]
    assert {
        pin["target_object_version_id"] for pin in pins if pin["relationship_type"] == "ATTACHMENT"
    } == {conclusion, first, second}

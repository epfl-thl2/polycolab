"""Version proposal application preserves pins, complete content, and replay."""

from copy import deepcopy
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalogue_api import enable
from test_proposals_api import _proposal_run, _proposal_source_event, headers
from test_research_domain import create_project
from test_version_api import create_versioned, snapshot

from polycolab.agents.context import manifest_for_run
from polycolab.agents.proposals import ProposalInvalid, submit_proposal
from polycolab.db.models import SqlAgentRun, SqlObjectRevision, SqlProposalChange, SqlResearchObject
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.entities.enums import ProvenanceKind


def submit(
    client: TestClient, project: str, pins: list[str], changes: list[dict[str, Any]]
) -> tuple[str, list[str]]:
    session_id, run_id = _proposal_run(client, project, pins)
    with cast(Any, client.app).state.session_factory() as db:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        cursors = _proposal_source_event(db, run, "versions")
        arguments = {
            "project_id": UUID(project),
            "session_id": UUID(session_id),
            "run_id": run.id,
            "agent_version_id": run.agent_version_id,
            "context_manifest_id": manifest.id,
            "idempotency_key": "versions",
            "summary": "Version proposals",
            "changes": changes,
            "trusted_source_event_cursors": cursors,
            "trusted_source_invocation_key": "versions",
        }
        proposal = submit_proposal(db, **arguments)
        assert submit_proposal(db, **arguments).id == proposal.id
        rows = list(
            db.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == proposal.id)
                .order_by(SqlProposalChange.ordinal)
            )
        )
        return str(proposal.id), [str(row.id) for row in rows]


def test_version_proposals_apply_complete_snapshots_and_replay_atomically(
    client: TestClient,
) -> None:
    enable(client)
    project = create_project(client)
    original = create_versioned(client, project, snapshot())
    other = create_versioned(client, project, snapshot())
    value = snapshot()
    value["content"].update(content_md="New exact content", assumptions_md="Explicit assumptions")
    value["change_summary"] = "A complete replacement"
    note = snapshot()
    note["kind"] = "NOTE"
    note["content"].pop("statement_label", None)
    changes = [
        {"kind": "CREATE_OBJECT", "snapshot": note},
        {
            "kind": "CREATE_OBJECT_VERSION",
            "object_id": original["object_id"],
            "expected_current_object_version_id": original["id"],
            "snapshot": value,
        },
        {
            "kind": "CREATE_RELATIONSHIP",
            "relationship": {
                "direction": "BIDIRECTIONAL",
                "relationship_type": "EQUIVALENT_TO",
                "first_object_version_id": original["id"],
                "second_object_version_id": other["id"],
            },
        },
        {
            "kind": "CREATE_COMMENT",
            "object_id": original["object_id"],
            "object_version_id": original["id"],
            "body_md": "Pinned to the old version",
        },
    ]
    proposal, identifiers = submit(client, project, [original["id"], other["id"]], changes)
    unpinned = create_versioned(client, project, snapshot())
    edited = deepcopy(changes[0])
    edited["snapshot"]["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": unpinned["id"]}
    ]
    rejected = client.post(
        f"/api/v1/proposals/{proposal}/changes/{identifiers[0]}/accept",
        headers={**headers("owner"), "Idempotency-Key": "unpin-edit"},
        json={"payload": edited},
    )
    assert rejected.status_code == 422, rejected.text
    path = f"/api/v1/proposals/{proposal}/decisions"
    body = {
        "decisions": [{"change_id": identifier, "action": "ACCEPT"} for identifier in identifiers]
    }
    auth = {**headers("owner"), "Idempotency-Key": "accept-versions"}
    response = client.post(path, headers=auth, json=body)
    assert response.status_code == 200, response.text
    assert client.post(path, headers=auth, json=body).json() == response.json()
    assert all(item["status"] == "ACCEPTED" for item in response.json())
    exact = client.get(
        f"/api/v1/versions/{response.json()[1]['applied_entity_id']}", headers=headers("owner")
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["content"] == value["content"]
    assert exact.json()["change_summary"] == value["change_summary"]
    assert exact.json()["previous_object_version_id"] == original["id"]
    assert exact.json()["authorship"]["actor_kind"] == "AGENT"
    with cast(Any, client.app).state.session_factory() as db:
        created = db.get(SqlResearchObject, UUID(response.json()[0]["applied_entity_id"]))
        revised = db.get(SqlObjectRevision, UUID(response.json()[1]["applied_entity_id"]))
        relation = db.get(
            SqlObjectVersionRelationship, UUID(response.json()[2]["applied_entity_id"])
        )
        assert created.provenance_kind is ProvenanceKind.AGENT_PROPOSAL
        assert revised.provenance_kind is ProvenanceKind.AGENT_PROPOSAL
        assert relation.provenance_kind is ProvenanceKind.AGENT_PROPOSAL
    old = client.get(f"/api/v1/versions/{original['id']}", headers=headers("owner"))
    assert old.json()["content"] == original["content"]


def test_version_proposal_rejects_unpinned_structural_inputs(client: TestClient) -> None:
    enable(client)
    project = create_project(client)
    original = create_versioned(client, project, snapshot())
    value = deepcopy(snapshot())
    value["kind"] = "PROOF"
    value["content"].pop("statement_label", None)
    value["content"]["reported_progress"] = "POTENTIAL"
    value["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": original["id"]}
        for role in ("CONCLUSION", "ATTACHMENT")
    ]
    with pytest.raises(ProposalInvalid):
        submit(client, project, [], [{"kind": "CREATE_OBJECT", "snapshot": value}])


@pytest.mark.parametrize("batch", [False, True])
def test_review_http_rejects_legacy_and_incomplete_edits_before_mutation(
    client: TestClient, batch: bool
) -> None:
    enable(client)
    project = create_project(client)
    proposal, identifiers = submit(
        client, project, [], [{"kind": "CREATE_OBJECT", "snapshot": snapshot()}]
    )
    legacy = {
        "kind": "CREATE_OBJECT",
        "object_kind": "CLAIM",
        "title": "Legacy",
        "content_md": "Legacy",
    }
    incomplete = snapshot()
    del incomplete["structural_relationships"]
    for payload in (legacy, {"kind": "CREATE_OBJECT", "snapshot": incomplete}):
        path = (
            f"/api/v1/proposals/{proposal}/decisions"
            if batch
            else f"/api/v1/proposals/{proposal}/changes/{identifiers[0]}/accept"
        )
        body = (
            {"decisions": [{"change_id": identifiers[0], "action": "ACCEPT", "payload": payload}]}
            if batch
            else {"payload": payload}
        )
        response = client.post(
            path, headers={**headers("owner"), "Idempotency-Key": "invalid-edit"}, json=body
        )
        assert response.status_code == 422, response.text
    detail = client.get(f"/api/v1/proposals/{proposal}", headers=headers("owner"))
    assert detail.json()["changes"][0]["status"] == "PENDING"

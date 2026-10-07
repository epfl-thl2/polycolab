"""Version-shaped retries recognize exact committed historical edits only."""

from copy import deepcopy
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalogue_api import enable
from test_proposal_version_application import submit
from test_proposals_api import headers
from test_research_domain import create_workspace
from test_version_api import create_versioned, snapshot

from polycolab.agents.proposals import BatchDecisionInput, accept_change, decide_changes_atomically
from polycolab.db.models import (
    SqlProposal,
    SqlProposalChange,
    SqlProposalChangeDecision,
    SqlProposalDecisionBatch,
    SqlUser,
)
from polycolab.entities.enums import ProposalDecisionAction


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("kind", ["version", "relationship", "comment"])
def test_projected_historical_edit_replays_without_rewriting_audit(
    client: TestClient, batch: bool, kind: str
) -> None:
    enable(client)
    project = create_workspace(client)
    first = create_versioned(client, project, snapshot())
    second = create_versioned(client, project, snapshot())
    legacy: dict[str, Any]
    if kind == "version":
        legacy = {
            "kind": "CREATE_REVISION",
            "object_id": first["object_id"],
            "base_revision_id": first["id"],
            "title": "Original",
            "content_md": "Original",
        }
        field = "content_md"
    elif kind == "relationship":
        legacy = {
            "kind": "CREATE_RELATION",
            "source_revision_id": second["id"],
            "target_revision_id": first["id"],
            "relation_type": "EQUIVALENT_TO",
            "rationale": "Original",
        }
        field = "rationale"
    else:
        legacy = {
            "kind": "CREATE_COMMENT",
            "object_id": first["object_id"],
            "revision_id": first["id"],
            "body_md": "Original",
        }
        field = "body_md"
    rejected_comment = {
        "kind": "CREATE_COMMENT",
        "object_id": first["object_id"],
        "object_version_id": first["id"],
        "body_md": "Not accepted",
    }
    proposal_id, changes = submit(
        client,
        project,
        [first["id"], second["id"]],
        [legacy, rejected_comment] if batch else [legacy],
    )
    owner_id = UUID(client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    edited = {**legacy, field: "Committed historical edit"}
    factory = cast(Any, client.app).state.session_factory
    with factory() as db:
        proposal = db.get(SqlProposal, UUID(proposal_id))
        owner = db.get(SqlUser, owner_id)
        assert proposal and owner
        if batch:
            accepted = decide_changes_atomically(
                db,
                proposal=proposal,
                decider=owner,
                idempotency_key="historical-edit",
                decisions=[
                    BatchDecisionInput(
                        UUID(changes[0]), ProposalDecisionAction.ACCEPT, edited, None
                    ),
                    BatchDecisionInput(UUID(changes[1]), ProposalDecisionAction.REJECT, None, "No"),
                ],
            )[0]
        else:
            accepted = accept_change(
                db,
                proposal=proposal,
                change_id=UUID(changes[0]),
                decider=owner,
                idempotency_key="historical-edit",
                edited_payload=edited,
            )
        applied_id = str(accepted.applied_entity_id)
        stored_payload = deepcopy(accepted.payload)
        decision_digests = sorted(db.scalars(select(SqlProposalChangeDecision.request_digest)))
        batch_digest = db.scalar(select(SqlProposalDecisionBatch.request_digest))
    detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("owner")).json()
    projected = detail["changes"][0]["payload"]
    path = (
        f"/api/v1/proposals/{proposal_id}/decisions"
        if batch
        else (f"/api/v1/proposals/{proposal_id}/changes/{changes[0]}/accept")
    )

    def retry(payload: dict[str, Any] | None, key: str = "historical-edit") -> Any:
        body: dict[str, Any] = {"payload": payload} if payload is not None else {}
        if batch:
            body = {
                "decisions": [
                    {"change_id": changes[0], "action": "ACCEPT", **body},
                    {"change_id": changes[1], "action": "REJECT", "reason": "No"},
                ]
            }
        return client.post(path, headers={**headers("owner"), "Idempotency-Key": key}, json=body)

    replay = retry(projected)
    assert replay.status_code == 200, replay.text
    result = replay.json()[0] if batch else replay.json()
    assert result["applied_entity_id"] == applied_id
    assert retry(projected, "different-key").status_code == 409
    assert retry(None).status_code == 409  # Edited and unchanged acceptances are distinct.
    assert retry(edited).status_code == 422  # Historical HTTP writes remain retired.
    changed = deepcopy(projected)
    if kind == "version":
        changed["snapshot"]["content"]["assumptions_md"] = "Different assumptions"
    elif kind == "relationship":
        changed["relationship"]["description"] = "Different rationale"
    else:
        changed["body_md"] = "Different comment"
    assert retry(changed).status_code == 409
    if batch:
        partial = client.post(
            path,
            headers={**headers("owner"), "Idempotency-Key": "historical-edit"},
            json={
                "decisions": [{"change_id": changes[0], "action": "ACCEPT", "payload": projected}]
            },
        )
        assert partial.status_code == 409
    with factory() as db:
        assert db.get(SqlProposalChange, UUID(changes[0])).payload == stored_payload
        assert (
            sorted(db.scalars(select(SqlProposalChangeDecision.request_digest))) == decision_digests
        )
        assert db.scalar(select(SqlProposalDecisionBatch.request_digest)) == batch_digest

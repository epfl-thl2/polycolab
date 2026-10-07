import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, headers
from test_research_structure import proof_snapshot, saved_version, targets

from polycolab.access.actors import ActorOperation, agent_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlCorrespondenceAssessment,
    SqlMutationReceipt,
    SqlRevisionEndorsement,
)
from polycolab.platform.outbox import canonical_digest
from polycolab.research import assurance
from polycolab.research.contracts import EndorsementWrite


def proof_payload(conclusion_id: str, premise_ids: list[str], *, title: str) -> dict[str, Any]:
    return {
        "destination": {"kind": "library", "statement_object_version_id": conclusion_id},
        "snapshot": proof_snapshot(conclusion_id, title, premise_ids),
    }


def test_alternative_proofs_keep_joint_premises_and_reject_only_dependency_cycles(
    client: TestClient,
) -> None:
    app = enable(client)
    conclusion = admit(client, "conclusion")
    first = admit(client, "first-premise")
    second = admit(client, "second-premise")

    proof = client.post(
        "/api/v1/objects",
        headers=headers(key="proof-one"),
        json=proof_payload(
            conclusion["object_version_id"],
            [first["object_version_id"], second["object_version_id"]],
            title="First proof",
        ),
    )
    assert proof.status_code == 201, proof.text
    exact = saved_version(client, proof.json())
    assert targets(exact, "CONCLUSION") == [conclusion["object_version_id"]]
    assert targets(exact, "PREMISE") == [first["object_version_id"], second["object_version_id"]]
    assert exact["content"]["reported_progress"] == "COMPLETE"

    alternative = client.post(
        "/api/v1/objects",
        headers=headers(key="proof-two"),
        json=proof_payload(
            conclusion["object_version_id"],
            [second["object_version_id"]],
            title="Alternative proof",
        ),
    )
    assert alternative.status_code == 201, alternative.text
    assert targets(saved_version(client, alternative.json()), "PREMISE") == [
        second["object_version_id"]
    ]

    # Ordinary research associations may cycle.
    for index, (source, target, relation_type) in enumerate(
        (
            (conclusion["object_version_id"], first["object_version_id"], "IMPLIES"),
            (first["object_version_id"], conclusion["object_version_id"], "EQUIVALENT_TO"),
        )
    ):
        relation = client.post(
            "/api/v1/relations",
            headers=headers(key=f"ordinary-{index}"),
            json={
                "destination": {"kind": "library", "statement_object_version_id": source},
                "relationship_type": relation_type,
                "description": "Exploratory association",
                **(
                    {
                        "direction": "BIDIRECTIONAL",
                        "first_object_version_id": source,
                        "second_object_version_id": target,
                    }
                    if relation_type == "EQUIVALENT_TO"
                    else {
                        "direction": "UNIDIRECTIONAL",
                        "source_object_version_id": source,
                        "target_object_version_id": target,
                    }
                ),
            },
        )
        assert relation.status_code == 201, relation.text

    cycle = client.post(
        "/api/v1/objects",
        headers=headers(key="cyclic-proof"),
        json=proof_payload(
            first["object_version_id"], [conclusion["object_version_id"]], title="Circular argument"
        ),
    )
    assert cycle.status_code == 409
    with app.state.session_factory() as db:
        hidden = db.get(SqlCatalogueEntry, UUID(first["entry_id"]))
        assert hidden is not None
        hidden.hidden = True
        db.commit()
    assert client.get(f"/api/v1/versions/{exact['id']}").status_code == 404


def test_assurance_is_historical_revision_pinned_and_does_not_inherit(
    client: TestClient,
) -> None:
    app = enable(client)
    conclusion = admit(client, "assurance-conclusion")
    proof = client.post(
        "/api/v1/objects",
        headers=headers(key="assured-proof"),
        json=proof_payload(conclusion["object_version_id"], [], title="Assured proof"),
    ).json()
    proof = saved_version(client, proof)
    endorsement = {
        "object_version_id": proof["id"],
        "active": True,
        "rationale": "I checked the informal argument",
    }
    first = client.post(
        "/api/v1/assurance/endorsements",
        headers=headers(key="endorse"),
        json=endorsement,
    )
    assert first.status_code == 201, first.text
    assert first.json()["object_version_id"] == proof["id"]
    assert "revision_id" not in first.json()
    assert (
        client.post(
            "/api/v1/assurance/endorsements",
            headers=headers(key="legacy-endorsement"),
            json={"revision_id": proof["id"], "active": True, "rationale": "Old field"},
        ).status_code
        == 422
    )
    with app.state.session_factory() as db:
        receipt = db.query(SqlMutationReceipt).filter_by(operation="assurance.endorse").one()
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "project_id": None,
                    "revision_id": proof["id"],
                    "active": True,
                    "rationale": endorsement["rationale"],
                },
            }
        )
    assert (
        client.post(
            "/api/v1/assurance/endorsements",
            headers=headers(key="endorse"),
            json=endorsement,
        ).json()
        == first.json()
    )
    changed = dict(endorsement, active=False)
    assert (
        client.post(
            "/api/v1/assurance/endorsements",
            headers=headers(key="endorse"),
            json=changed,
        ).status_code
        == 409
    )
    correspondence = client.post(
        "/api/v1/assurance/correspondence",
        headers=headers(key="correspondence"),
        json={
            "object_version_id": proof["id"],
            "statement_object_version_id": conclusion["object_version_id"],
            "status": "PARTIAL",
            "rationale": "The argument proves the finite case only",
        },
    )
    assert correspondence.status_code == 201, correspondence.text
    assert correspondence.json()["object_version_id"] == proof["id"]
    assert correspondence.json()["statement_object_version_id"] == conclusion["object_version_id"]
    assert "statement_revision_id" not in correspondence.json()
    assert (
        client.post(
            "/api/v1/assurance/correspondence",
            headers=headers(key="legacy-correspondence"),
            json={
                "revision_id": proof["id"],
                "statement_revision_id": conclusion["object_version_id"],
                "status": "PARTIAL",
                "rationale": "Old fields",
            },
        ).status_code
        == 422
    )
    with app.state.session_factory() as db:
        receipt = db.query(SqlMutationReceipt).filter_by(operation="assurance.correspondence").one()
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "project_id": None,
                    "revision_id": proof["id"],
                    "statement_revision_id": conclusion["object_version_id"],
                    "status": "PARTIAL",
                    "rationale": "The argument proves the finite case only",
                },
            }
        )
    history = client.get(f"/api/v1/assurance/{proof['id']}").json()
    assert [item["active"] for item in history["endorsements"]] == [True]
    assert [item["status"] for item in history["correspondence"]] == ["PARTIAL"]
    assert "user_id" not in str(history)

    updated = client.post(
        f"/api/v1/objects/{proof['object_id']}/versions",
        headers=headers(key="revise-proof"),
        json={
            "expected_current_object_version_id": proof["id"],
            "snapshot": proof_snapshot(conclusion["object_version_id"], "Revised proof"),
        },
    )
    assert updated.status_code == 201, updated.text
    updated_version = saved_version(client, updated.json())
    assert client.get(f"/api/v1/assurance/{updated_version['id']}").json() == {
        "object_version_id": updated_version["id"],
        "endorsements": [],
        "correspondence": [],
        "next_cursor": None,
    }
    assert client.get(f"/api/v1/assurance/{proof['id']}").json() == history


def test_assurance_current_positions_are_per_assessor_and_history_is_chronological(
    client: TestClient,
) -> None:
    app = enable(client)
    conclusion = admit(client, "research-assurance-conclusion")
    proof = client.post(
        "/api/v1/objects",
        headers=headers(key="beta-assurance-proof"),
        json=proof_payload(conclusion["object_version_id"], [], title="Beta assurance proof"),
    ).json()
    proof = saved_version(client, proof)
    client.get("/api/v1/users/me", headers=headers("contributor"))

    created: list[tuple[str, str]] = []
    for actor, active, rationale in (
        ("owner", True, "owner endorses"),
        ("contributor", True, "contributor endorses"),
        ("owner", False, "owner withdraws"),
    ):
        response = client.post(
            "/api/v1/assurance/endorsements",
            headers=headers(actor, key=rationale.replace(" ", "-")),
            json={
                "object_version_id": proof["id"],
                "active": active,
                "rationale": rationale,
            },
        )
        assert response.status_code == 201, response.text
        created.append(("endorsement", response.json()["id"]))
    for actor, status, rationale in (
        ("owner", "MATCHES", "owner initially matches"),
        ("contributor", "MISMATCH", "contributor disagrees"),
        ("owner", "PARTIAL", "owner sees a gap"),
    ):
        response = client.post(
            "/api/v1/assurance/correspondence",
            headers=headers(actor, key=rationale.replace(" ", "-")),
            json={
                "object_version_id": proof["id"],
                "statement_object_version_id": conclusion["object_version_id"],
                "status": status,
                "rationale": rationale,
            },
        )
        assert response.status_code == 201, response.text
        created.append(("correspondence", response.json()["id"]))

    # Deliberately make UUID order the reverse of chronological order.
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with app.state.session_factory() as db:
        for index, (kind, row_id) in enumerate(created):
            model = SqlRevisionEndorsement if kind == "endorsement" else SqlCorrespondenceAssessment
            row = db.get(model, UUID(row_id))
            assert row is not None
            row.id = UUID(int=100 - index)
            row.created_at = start + timedelta(seconds=index)
            created[index] = (kind, str(row.id))
        db.commit()

    current_url = f"/api/v1/assurance/{proof['id']}/current"
    current = client.get(current_url).json()
    assert {(item["active"], item["rationale"]) for item in current["endorsements"]} == {
        (True, "contributor endorses"),
        (False, "owner withdraws"),
    }
    assert {item["status"] for item in current["correspondence"]} == {
        "PARTIAL",
        "MISMATCH",
    }
    assert len({item["assessor_id"] for item in current["endorsements"]}) == 2
    assert all(
        item["statement_object_version_id"] == conclusion["object_version_id"]
        for item in current["correspondence"]
    )

    history_url = f"/api/v1/assurance/{proof['id']}"
    rationales: list[str] = []
    cursor = None
    while True:
        response = client.get(
            history_url, params={"limit": 2, **({"cursor": cursor} if cursor else {})}
        )
        assert response.status_code == 200, response.text
        page = response.json()
        rationales.extend(
            item["rationale"]
            for item in sorted(
                page["endorsements"] + page["correspondence"],
                key=lambda item: item["created_at"],
            )
        )
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert rationales == [
        "owner endorses",
        "contributor endorses",
        "owner withdraws",
        "owner initially matches",
        "contributor disagrees",
        "owner sees a gap",
    ]
    assert client.get(current_url).json() == current
    malformed_typed_cursor = base64.urlsafe_b64encode(
        json.dumps(["v1", 7, "endorsement", 9]).encode()
    ).decode()
    for invalid_cursor in ("not-a-cursor", malformed_typed_cursor):
        assert client.get(history_url, params={"cursor": invalid_cursor}).status_code == 409


def test_agent_cannot_endorse_even_with_contribution_authority(client: TestClient) -> None:
    app = enable(client)
    statement = admit(client, "agent-endorsement")
    user_id = UUID(client.get("/api/v1/users/me", headers=headers()).json()["id"])
    actor = agent_actor(
        sponsor_user_id=user_id,
        agent_version_id=uuid4(),
        run_id=uuid4(),
        capability_id=uuid4(),
        session_id=uuid4(),
        context_manifest_id=uuid4(),
        project_id=uuid4(),
        operation_scope=frozenset({ActorOperation.CONTRIBUTION_CREATE}),
    )
    with app.state.session_factory() as db:
        with pytest.raises(AuthorizationDenied):
            assurance.endorse(
                db,
                actor=actor,
                payload=EndorsementWrite(
                    revision_id=UUID(statement["object_version_id"]),
                    active=True,
                    rationale="Agents cannot endorse",
                ),
                key="agent-endorsement",
            )

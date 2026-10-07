"""Public corrections preserve submitted text and require current human authority."""

from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, formulation, headers

from polycolab.db.models import SqlCorrectionDecision
from polycolab.platform.outbox import canonical_digest


def correction_command(proposed: dict[str, Any]) -> dict[str, Any]:
    target = proposed["base_revision_id"]
    return {
        "destination": {"kind": "library", "statement_object_version_id": target},
        "snapshot": {
            "kind": "NOTE",
            "content": {
                "title": "Correction",
                "content_md": "Proposed correction",
                "assumptions_md": "None",
                "reported_outcome": None,
                "explanation_md": None,
            },
            "structural_relationships": [
                {"relationship_type": "ATTACHMENT", "target_object_version_id": target}
            ],
        },
        "catalogue_suggestion": {
            **{key: value for key, value in proposed.items() if key != "base_revision_id"},
            "expected_current_object_version_id": target,
        },
    }


def test_public_correction_edit_accept_and_retry(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    proposed = {key: value for key, value in formulation().items() if key != "kind"}
    proposed.update(base_revision_id=entry["object_version_id"], title="Suggested formulation")
    response = client.post(
        "/api/v1/objects",
        headers=headers("outsider", "suggest"),
        json=correction_command(proposed),
    )
    assert response.status_code == 201, response.text
    revision_id = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    url = f"/api/v1/records/{revision_id}/decision"
    decision = {
        "action": "EDIT_AND_ACCEPT",
        "edited": {
            **correction_command(proposed)["catalogue_suggestion"],
            "title": "Human refined formulation",
        },
        "reason": "Clarified the correction",
    }
    assert client.post(url, headers=headers("outsider", "deny"), json=decision).status_code == 403
    accepted = client.post(url, headers=headers(key="accept"), json=decision)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["suggestion_object_version_id"] == revision_id
    assert accepted.json()["decided_object_version_id"] is not None
    assert "suggestion_revision_id" not in accepted.json()
    assert "decided_revision_id" not in accepted.json()
    assert client.post(url, headers=headers(key="accept"), json=decision).json() == accepted.json()
    historical = {
        **decision,
        "edited": {**proposed, "title": "Human refined formulation", "review_rationale": None},
    }
    with app.state.session_factory() as db:
        stored = db.get(SqlCorrectionDecision, UUID(revision_id))
        assert stored is not None
        assert stored.request_digest == canonical_digest(historical)
    assert client.post(url, headers=headers(key="old-shape"), json=historical).status_code == 422
    assert (
        client.get(f"/api/v1/catalogue/{entry['entry_id']}").json()["object_version"]["content"][
            "title"
        ]
        == "Human refined formulation"
    )
    assert (
        client.get(f"/api/v1/records/{revision_id}").json()["catalogue"]["suggestion"]["title"]
        == "Suggested formulation"
    )
    public = client.get(f"/api/v1/records/{revision_id}/decision")
    assert public.json() == accepted.json()
    assert "decided_by_user_id" not in public.text


def test_stale_correction_acceptance_is_atomic_and_rejection_retains_it(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    proposed = {key: value for key, value in formulation().items() if key != "kind"}
    proposed.update(base_revision_id=entry["object_version_id"])
    suggestion = client.post(
        "/api/v1/objects",
        headers=headers(key="suggest"),
        json=correction_command(proposed),
    ).json()
    suggestion_version_id = next(
        row["entity_id"] for row in suggestion["outputs"] if row["entity_type"] == "OBJECT_VERSION"
    )
    updated = client.post(
        f"/api/v1/catalogue/{entry['entry_id']}/versions",
        headers=headers(key="update"),
        json={
            **{key: value for key, value in proposed.items() if key != "base_revision_id"},
            "expected_current_object_version_id": proposed["base_revision_id"],
            "title": "Newer base",
        },
    )
    assert updated.status_code == 201
    url = f"/api/v1/records/{suggestion_version_id}/decision"
    assert (
        client.post(
            url,
            headers=headers(key="stale"),
            json={"action": "ACCEPT", "reason": "Accept correction"},
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/records/{suggestion_version_id}/decision").json() is None
    rejected = client.post(
        url,
        headers=headers(key="reject"),
        json={"action": "REJECT", "reason": "Superseded by a newer formulation"},
    )
    assert rejected.status_code == 200, rejected.text
    assert client.get(f"/api/v1/records/{suggestion_version_id}").status_code == 200

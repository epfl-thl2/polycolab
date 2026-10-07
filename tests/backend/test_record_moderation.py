"""Moderation removes exact record histories from every public read path."""

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalogue_api import admit, enable, headers
from test_library_api import attempt_payload
from test_research_structure import saved_version

from polycolab.db.models import SqlMutationReceipt
from polycolab.platform.outbox import canonical_digest


def test_record_hide_restore_audit_and_public_search(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    created = client.post(
        "/api/v1/objects",
        headers=headers(key="record"),
        json=attempt_payload(entry["object_version_id"]),
    ).json()
    created = saved_version(client, created)
    url = f"/api/v1/records/objects/{created['object_id']}/moderation"
    payload = {
        "expected_current_object_version_id": created["id"],
        "hidden": True,
        "reason": "Abusive contribution",
    }
    assert client.post(url, headers=headers(key="deny"), json=payload).status_code == 403
    user = client.get("/api/v1/users/me", headers=headers()).json()
    assigned = client.put(
        f"/api/v1/catalogue-moderators/{user['id']}",
        headers=headers(),
        json={"active": True, "reason": "Test moderator"},
    )
    assert assigned.status_code == 204, assigned.text
    assert (
        client.post(
            url,
            headers=headers(key="legacy-guard"),
            json={"base_revision_id": created["id"], "hidden": True, "reason": "Old request"},
        ).status_code
        == 422
    )
    hidden = client.post(url, headers=headers(key="hide"), json=payload)
    assert hidden.status_code == 200, hidden.text
    assert client.post(url, headers=headers(key="hide"), json=payload).json() == hidden.json()
    assert (
        client.post(
            url, headers=headers(key="hide"), json={**payload, "reason": "Different request"}
        ).status_code
        == 409
    )
    with app.state.session_factory() as session:
        receipt = session.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.operation == "record.moderate",
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("hide"),
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "object_id": created["object_id"],
                    "base_revision_id": created["id"],
                    "hidden": True,
                    "reason": "Abusive contribution",
                },
            }
        )
    assert hidden.json()["object_version_id"] == created["id"]
    assert "revision_id" not in hidden.json()
    assert client.get(f"/api/v1/records/{created['id']}").status_code == 404
    assert client.get("/api/v1/discovery", params={"q": "induction"}).json()["items"] == []
    assert (
        client.get("/api/v1/records", params={"object_id": created["object_id"]}).json()["items"]
        == []
    )
    assert (
        client.post(
            url,
            headers=headers(key="restore"),
            json={**payload, "hidden": False, "reason": "Appeal accepted"},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/records/{created['id']}").status_code == 200
    assert len(client.get(url, headers=headers()).json()) == 2

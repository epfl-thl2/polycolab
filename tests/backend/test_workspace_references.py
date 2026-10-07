"""Private pins preserve identity, history, current permissions, and retry semantics."""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from test_catalogue_api import admit, enable, formulation, headers

from polycolab.db.models import SqlCatalogueEntry, SqlMutationReceipt, SqlProject, SqlResearchObject
from polycolab.platform.outbox import canonical_digest


def test_pin_reuse_explicit_upgrade_and_private_history(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    public_before = client.get("/api/v1/catalogue").json()
    payload = {
        "object_version_id": entry["object_version_id"],
        "workspace_visibility": "PRIVATE",
        "workspace_name": "Private exploration",
        "reason": "Work privately",
    }
    first = client.post("/api/v1/workspace-references", headers=headers(key="pin"), json=payload)
    assert first.status_code == 201, first.text
    pin = first.json()
    assert pin["object_id"] == entry["entry_id"]
    assert pin["object_version_id"] == entry["object_version_id"]
    assert pin["previous_reference_version_id"] is None
    assert pin["reference_version_id"] != pin["object_version_id"]
    assert not {"revision_id", "version_id", "base_version_id", "latest_revision_id"} & pin.keys()
    assert (
        client.post("/api/v1/workspace-references", headers=headers(key="pin"), json=payload).json()
        == pin
    )
    assert (
        client.post(
            "/api/v1/workspace-references", headers=headers(key="reuse"), json=payload
        ).json()
        == pin
    )
    assert client.get("/api/v1/catalogue").json() == public_before
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SqlProject)) == 1
        assert db.scalar(select(func.count()).select_from(SqlResearchObject)) == 1
        receipt = db.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.operation == "reference.create",
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("pin"),
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "revision_id": entry["object_version_id"],
                    "project_id": None,
                    "workspace_name": "Private exploration",
                    "reason": "Work privately",
                },
            }
        )
    revision = client.post(
        f"/api/v1/catalogue/{entry['entry_id']}/versions",
        headers=headers(key="revise"),
        json={
            **{key: value for key, value in formulation().items() if key != "kind"},
            "expected_current_object_version_id": entry["object_version_id"],
            "title": "Revised formulation",
        },
    )
    assert revision.status_code == 201, revision.text
    target = revision.json()["object_version_id"]
    params = {"workspace_id": pin["workspace_id"]}
    assert (
        client.get("/api/v1/workspace-references", headers=headers(), params=params).json()[
            "items"
        ][0]["object_version_id"]
        == entry["object_version_id"]
    )
    assert (
        client.post(
            "/api/v1/workspace-references",
            headers=headers(key="no-implicit-upgrade"),
            json={**payload, "object_version_id": target},
        ).status_code
        == 409
    )
    upgrade = {
        "expected_current_reference_version_id": pin["reference_version_id"],
        "object_version_id": target,
        "reason": "Use updated formulation",
    }
    endpoint = f"/api/v1/workspace-references/{pin['id']}/versions"
    changed = client.post(endpoint, headers=headers(key="upgrade"), json=upgrade)
    assert changed.status_code == 200, changed.text
    assert changed.json()["number"] == 2
    assert changed.json()["previous_reference_version_id"] == pin["reference_version_id"]
    assert changed.json()["object_version_id"] == target
    assert changed.json()["reference_version_id"] != target
    with app.state.session_factory() as db:
        receipt = db.scalar(
            select(SqlMutationReceipt).where(
                SqlMutationReceipt.operation == "reference.upgrade",
                SqlMutationReceipt.idempotency_key_digest == canonical_digest("upgrade"),
            )
        )
        assert receipt is not None
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    "reference_id": pin["id"],
                    "base_version_id": pin["reference_version_id"],
                    "revision_id": target,
                    "reason": "Use updated formulation",
                },
            }
        )
    assert (
        client.post(endpoint, headers=headers(key="upgrade"), json=upgrade).json() == changed.json()
    )
    assert client.post(endpoint, headers=headers(key="stale"), json=upgrade).status_code == 409
    assert (
        client.post(
            endpoint,
            headers=headers(key="wrong-version-plane"),
            json={**upgrade, "expected_current_reference_version_id": target},
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint,
            headers=headers(key="legacy-guard"),
            json={
                "base_version_id": pin["reference_version_id"],
                "revision_id": target,
                "reason": "Old fields are not aliases",
            },
        ).status_code
        == 422
    )
    history = client.get(
        "/api/v1/workspace-references",
        headers=headers(),
        params={**params, "reference_id": pin["id"]},
    ).json()["items"]
    assert {row["object_version_id"] for row in history} == {entry["object_version_id"], target}
    assert client.get(
        "/api/v1/workspace-references", headers=headers("outsider"), params=params
    ).status_code in (403, 404)
    with app.state.session_factory() as db:
        value = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert value is not None
        value.hidden = True
        db.commit()
    hidden = client.get("/api/v1/workspace-references", headers=headers(), params=params).json()[
        "items"
    ][0]
    assert hidden["available"] is False and hidden["title"] is None
    assert client.post(endpoint, headers=headers(key="upgrade"), json=upgrade).status_code == 404


def test_invalid_reference_rolls_back_new_workspace(client: TestClient) -> None:
    app = enable(client)
    response = client.post(
        "/api/v1/workspace-references",
        headers=headers(),
        json={"object_version_id": "00000000-0000-0000-0000-000000000002"},
    )
    assert response.status_code == 404
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(SqlProject)) == 0

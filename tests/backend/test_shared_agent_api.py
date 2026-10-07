"""Shared resource authority, stable actors, budgets and independent retry receipts."""

from typing import Any, cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from polycolab.db.models import SqlExternalAgentCredential, SqlExternalResearchRun


def test_retained_run_history_uses_object_version_inputs(client: TestClient) -> None:
    workspace, secret = setup(client)
    response = client.post("/api/v1/objects", headers=headers(secret), json=body(workspace["id"]))
    assert response.status_code == 201, response.text
    version_id = next(
        output["entity_id"]
        for output in response.json()["outputs"]
        if output["entity_type"] == "OBJECT_VERSION"
    )
    with cast(Any, client.app).state.session_factory() as session:
        credential = session.query(SqlExternalAgentCredential).one()
        historical = SqlExternalResearchRun(
            credential_id=credential.id,
            project_id=UUID(workspace["id"]),
            sponsor_user_id=credential.sponsor_user_id,
            client_request_id=uuid4(),
            input_revision_ids=[version_id],
        )
        session.add(historical)
        session.commit()
        run_id = historical.id
    exact = client.get(f"/api/v1/runs/{run_id}", headers=headers(secret))
    assert exact.status_code == 200, exact.text
    assert exact.json()["input_object_version_ids"] == [version_id]
    assert "input_revision_ids" not in exact.json()
    page = client.get("/api/v1/runs", headers=headers(secret))
    assert page.status_code == 200, page.text
    assert page.json()["items"] == [exact.json()]
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers("outsider")).status_code == 401
    _, other_secret = setup(client)
    assert client.get(f"/api/v1/runs/{run_id}", headers=headers(other_secret)).status_code == 404
    assert client.get("/api/v1/runs", headers=headers(other_secret)).json()["items"] == []
    with cast(Any, client.app).state.session_factory() as session:
        assert session.get(SqlExternalResearchRun, run_id).input_revision_ids == [version_id]


def headers(token: str = "owner", key: str = "write") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key}


def setup(client: TestClient) -> tuple[dict[str, Any], str]:
    workspace = client.post(
        "/api/v1/workspaces",
        headers=headers(),
        json={"visibility": "PRIVATE", "name": "Private research"},
    )
    assert workspace.status_code == 201
    identity = client.post(
        "/api/v1/account/agents", headers=headers(), json={"name": "Research agent"}
    )
    key = client.post(
        "/api/v1/account/agent-keys",
        headers=headers(),
        json={"name": "Key", "agent_id": identity.json()["id"]},
    )
    assert key.status_code == 201, key.text
    return cast(dict[str, Any], workspace.json()), str(key.json()["secret"])


def body(workspace: str) -> dict[str, Any]:
    return {
        "destination": {"kind": "workspace", "workspace_id": workspace},
        "snapshot": {
            "kind": "STATEMENT",
            "content": {
                "title": "Claim",
                "content_md": "A bound",
                "assumptions_md": "None",
                "reported_outcome": None,
                "explanation_md": None,
            },
            "structural_relationships": [],
            "change_summary": None,
        },
    }


def test_account_key_reads_future_memberships_and_writes_without_run(client: TestClient) -> None:
    workspace, secret = setup(client)
    future = client.post(
        "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": "Future"}
    ).json()
    listed = client.get("/api/v1/workspaces?scope=member", headers=headers(secret))
    assert {row["id"] for row in listed.json()["items"]} == {workspace["id"], future["id"]}
    written = client.post("/api/v1/objects", headers=headers(secret), json=body(future["id"]))
    assert written.status_code == 201, written.text
    assert written.json()["contribution_id"]
    assert client.get("/api/v1/activity").json()["items"] == []


def test_replay_conflict_and_revocation_authorize_before_receipt(client: TestClient) -> None:
    workspace, secret = setup(client)
    payload = body(workspace["id"])
    first = client.post("/api/v1/objects", headers=headers(secret), json=payload)
    assert first.status_code == 201
    before = client.get("/api/v1/me", headers=headers(secret)).json()
    replay = client.post("/api/v1/objects", headers=headers(secret), json=payload)
    assert replay.json() == {**first.json(), "replayed": True}
    assert (
        client.get("/api/v1/me", headers=headers(secret)).json()["mutations_remaining"]
        == before["mutations_remaining"]
    )
    assert (
        client.post(
            "/api/v1/objects",
            headers=headers(secret),
            json={
                **payload,
                "snapshot": {
                    **payload["snapshot"],
                    "content": {**payload["snapshot"]["content"], "title": "Changed"},
                },
            },
        ).status_code
        == 409
    )
    assert (
        client.delete(
            f"/api/v1/account/agent-keys/{before['credential_id']}", headers=headers()
        ).status_code
        == 204
    )
    assert client.post("/api/v1/objects", headers=headers(secret), json=payload).status_code == 401


def test_exhaustion_is_429_but_identity_remains_available(client: TestClient) -> None:
    _, secret = setup(client)
    identity = client.get("/api/v1/me", headers=headers(secret)).json()
    with cast(Any, client.app).state.session_factory() as session:
        key = session.get(SqlExternalAgentCredential, UUID(identity["credential_id"]))
        assert key
        key.request_count = key.max_requests
        session.commit()
    assert client.get("/api/v1/workspaces", headers=headers(secret)).status_code == 429
    assert client.get("/api/v1/me", headers=headers(secret)).status_code == 200


def test_keys_and_identities_are_human_owned(client: TestClient) -> None:
    _, secret = setup(client)
    identity = client.get("/api/v1/me", headers=headers(secret)).json()
    for path in ["/api/v1/account/agents", "/api/v1/account/agent-keys"]:
        assert client.get(path, headers=headers(secret)).status_code in {401, 403}
    assert (
        client.patch(
            f"/api/v1/account/agents/{identity['agent_id']}",
            headers=headers("outsider"),
            json={"name": "Stolen"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/v1/account/agent-keys",
            headers=headers("outsider"),
            json={"name": "Stolen", "agent_id": identity["agent_id"]},
        ).status_code
        == 403
    )
    renamed = client.patch(
        f"/api/v1/account/agents/{identity['agent_id']}",
        headers=headers(),
        json={"name": "Renamed"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["id"] == identity["agent_id"]


def test_invalid_bearer_never_downgrades_to_anonymous(client: TestClient) -> None:
    setup(client)
    for token in ["pca_invalid", "unknown"]:
        assert client.get("/api/v1/workspaces", headers=headers(token)).status_code == 401


def test_history_cursor_is_bound_to_filters(client: TestClient) -> None:
    workspace, secret = setup(client)
    for index in range(3):
        assert (
            client.post(
                "/api/v1/objects", headers=headers(secret, str(index)), json=body(workspace["id"])
            ).status_code
            == 201
        )
    first = client.get("/api/v1/activity?scope=member&limit=1", headers=headers(secret)).json()
    cursor = first["next_cursor"]
    assert cursor
    changed = client.get(
        "/api/v1/activity",
        headers=headers(secret),
        params={"scope": "public", "limit": 1, "cursor": cursor},
    )
    assert changed.status_code == 422
    second = client.get(
        "/api/v1/activity",
        headers=headers(secret),
        params={"scope": "member", "limit": 1, "cursor": cursor},
    )
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] != first["items"][0]["id"]


def test_external_run_creation_and_closure_are_retired(client: TestClient) -> None:
    workspace, secret = setup(client)
    assert client.post(
        "/api/v1/runs",
        headers=headers(secret),
        json={"workspace_id": workspace["id"], "client_request_id": str(uuid4())},
    ).status_code in {404, 405}
    assert client.post(
        f"/api/v1/runs/{uuid4()}/close", headers=headers(secret), json={"status": "COMPLETED"}
    ).status_code in {404, 405}
    assert (
        client.post(
            "/api/v1/objects",
            headers={"Authorization": f"Bearer {secret}"},
            json=body(workspace["id"]),
        ).status_code
        == 422
    )


def test_membership_loss_filters_history_and_denies_replay(client: TestClient) -> None:
    from test_research_domain import current_user_id

    workspace, secret = setup(client)
    other = client.post(
        "/api/v1/workspaces",
        headers=headers("contributor"),
        json={"visibility": "PRIVATE", "name": "Other"},
    ).json()
    owner = current_user_id(client, "owner")
    member_path = f"/api/v1/workspaces/{other['id']}/members"
    assert (
        client.post(
            member_path,
            headers=headers("contributor"),
            json={"user_id": owner, "role": "CONTRIBUTOR"},
        ).status_code
        == 201
    )
    payload = body(other["id"])
    assert client.post("/api/v1/objects", headers=headers(secret), json=payload).status_code == 201
    assert (
        client.delete(f"{member_path}/{owner}", headers=headers("contributor")).status_code == 204
    )
    assert client.post("/api/v1/objects", headers=headers(secret), json=payload).status_code in {
        403,
        404,
    }
    assert (
        client.get("/api/v1/activity?scope=member", headers=headers(secret)).json()["items"] == []
    )
    assert (
        client.post(
            "/api/v1/objects",
            headers=headers(secret, "other-workspace"),
            json=body(workspace["id"]),
        ).status_code
        == 201
    )


def test_contribution_outputs_are_exact_and_private(client: TestClient) -> None:
    workspace, secret = setup(client)
    receipt = client.post(
        "/api/v1/objects", headers=headers(secret), json=body(workspace["id"])
    ).json()
    path = f"/api/v1/contributions/{receipt['contribution_id']}"
    read = client.get(path, headers=headers(secret))
    assert read.status_code == 200
    assert {row["entity_id"] for row in read.json()["outputs"]} == {
        row["entity_id"] for row in receipt["outputs"]
    }
    assert client.get(path).status_code == 404
    assert client.get(path, headers=headers("outsider")).status_code == 404


def test_staging_is_owned_by_stable_agent_across_key_rotation(client: TestClient) -> None:
    import hashlib

    from test_artifacts import MemoryS3

    from polycolab.artifacts.storage import GarageStorage

    workspace, secret = setup(client)
    app = cast(Any, client.app)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "test")
    identity = client.get("/api/v1/me", headers=headers(secret)).json()["agent_id"]
    params = {
        "workspace_id": workspace["id"],
        "sha256": hashlib.sha256(b"abc").hexdigest(),
        "byte_length": 3,
    }
    upload = client.post(
        "/api/v1/artifacts", headers=headers(secret, "upload"), params=params, content=b"abc"
    )
    assert upload.status_code == 201, upload.text
    path = f"/api/v1/artifacts/{upload.json()['id']}"
    _, other = setup(client)
    assert client.get(path, headers=headers(other)).status_code == 404
    rotated = client.post(
        "/api/v1/account/agent-keys",
        headers=headers(),
        json={"name": "Rotated", "agent_id": identity},
    ).json()["secret"]
    assert client.get(path, headers=headers(rotated)).status_code == 200
    replay = client.post(
        "/api/v1/artifacts", headers=headers(rotated, "upload"), params=params, content=b"abc"
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == upload.json()["id"]
    assert (
        client.get("/api/v1/activity?scope=member", headers=headers(secret)).json()["items"] == []
    )


def test_archiving_preserves_member_history_and_denies_new_writes(client: TestClient) -> None:
    workspace, secret = setup(client)
    assert (
        client.post(
            "/api/v1/objects", headers=headers(secret), json=body(workspace["id"])
        ).status_code
        == 201
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{workspace['id']}", headers=headers(), json={"archived": True}
        ).status_code
        == 200
    )
    assert (
        len(client.get("/api/v1/activity?scope=member", headers=headers(secret)).json()["items"])
        == 1
    )
    assert (
        client.post(
            "/api/v1/objects", headers=headers(secret, "after-archive"), json=body(workspace["id"])
        ).status_code
        == 403
    )

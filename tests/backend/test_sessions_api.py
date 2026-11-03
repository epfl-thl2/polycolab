from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import event


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=headers("owner"),
        json={"name": "Agent research", "visibility": "PRIVATE"},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def create_profile(client: TestClient, token: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=headers(token),
        json={
            "display_name": "Model",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "research-model",
            "api_key": f"sk-{token}-secret",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def add_member(client: TestClient, project_id: str, token: str, role: str) -> None:
    user = client.get("/api/v1/users/me", headers=headers(token)).json()
    response = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=headers("owner"),
        json={"user_id": user["id"], "role": role},
    )
    assert response.status_code == 201, response.text


def create_session(client: TestClient, project_id: str, token: str = "owner") -> dict[str, object]:
    response = client.post(
        "/api/v1/sessions",
        headers=headers(token),
        json={
            "project_id": project_id,
            "agent_kind": "RESEARCHER",
            "title": "Main thread",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def send(
    client: TestClient,
    session_id: str,
    profile_id: str,
    token: str = "owner",
    **changes: object,
) -> Response:
    return cast(
        Response,
        client.post(
            f"/api/v1/sessions/{session_id}/events",
            headers=headers(token),
            json={
                "type": "message",
                "client_request_id": str(uuid4()),
                "content_md": "Investigate.",
                "gateway_profile_id": profile_id,
                **changes,
            },
        ),
    )


def interrupt(client: TestClient, session_id: str, run_id: str, token: str = "owner") -> Response:
    return cast(
        Response,
        client.post(
            f"/api/v1/sessions/{session_id}/events",
            headers=headers(token),
            json={"type": "interrupt", "run_id": run_id},
        ),
    )


def test_local_browser_can_read_pagination_cursor(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    origin = str(app.state.settings.allowed_origins[0]).rstrip("/")
    project_id = str(create_project(client)["id"])
    session_id = str(create_session(client, project_id)["id"])
    profile_id = str(create_profile(client, "owner")["id"])
    run_ids = []
    for _ in range(2):
        accepted = send(client, session_id, profile_id)
        assert accepted.status_code == 202, accepted.text
        run_id = accepted.json()["run"]["id"]
        run_ids.append(run_id)
        assert interrupt(client, session_id, run_id).status_code == 202
    first = client.get(
        f"/api/v1/sessions/{session_id}/runs",
        params={"limit": 1},
        headers={**headers("owner"), "Origin": origin},
    )
    assert first.status_code == 200
    assert "x-next-cursor" in first.headers["access-control-expose-headers"].lower()
    second = client.get(
        f"/api/v1/sessions/{session_id}/runs",
        params={"limit": 1, "cursor": first.headers["X-Next-Cursor"]},
        headers=headers("owner"),
    )
    assert [first.json()[0]["id"], second.json()[0]["id"]] == run_ids
    items = client.get(
        f"/api/v1/sessions/{session_id}/items",
        params={"limit": 1},
        headers=headers("owner"),
    )
    assert items.json()["items"][0]["type"] == "message"
    next_items = client.get(
        f"/api/v1/sessions/{session_id}/items",
        params={"cursor": items.json()["next_cursor"]},
        headers=headers("owner"),
    )
    assert next_items.json()["items"][0]["sequence"] > items.json()["items"][0]["sequence"]
    assert next_items.json()["items"][0]["type"] == "error"


def test_session_list_orders_by_latest_activity(client: TestClient) -> None:
    project_id = str(create_project(client)["id"])
    older = create_session(client, project_id)
    newer = create_session(client, project_id)
    assert older["latest_execution"] is None
    accepted = send(client, str(older["id"]), str(create_profile(client, "owner")["id"]))
    assert accepted.status_code == 202
    listed = client.get(
        "/api/v1/sessions",
        params={"project_id": project_id, "limit": 1},
        headers=headers("owner"),
    )
    assert listed.json()[0]["id"] == older["id"]
    assert listed.json()[0]["latest_execution"]["id"] == accepted.json()["run"]["id"]
    assert listed.json()[0]["latest_execution"]["status"] == "QUEUED"
    second = client.get(
        "/api/v1/sessions",
        params={"project_id": project_id, "cursor": listed.headers["X-Next-Cursor"]},
        headers=headers("owner"),
    )
    assert [value["id"] for value in second.json()] == [newer["id"]]


def test_session_run_summaries_are_batched(client: TestClient) -> None:
    project_id = str(create_project(client)["id"])
    profile_id = str(create_profile(client, "owner")["id"])
    for _ in range(4):
        session_id = str(create_session(client, project_id)["id"])
        accepted = send(client, session_id, profile_id)
        assert accepted.status_code == 202
        assert interrupt(client, session_id, accepted.json()["run"]["id"]).status_code == 202
    queries: list[str] = []

    def collect_queries(*args: object) -> None:
        queries.append(str(args[2]))

    engine = cast(FastAPI, client.app).state.engine
    event.listen(engine, "before_cursor_execute", collect_queries)
    try:
        listed = client.get(
            "/api/v1/sessions",
            params={"project_id": project_id},
            headers=headers("owner"),
        )
    finally:
        event.remove(engine, "before_cursor_execute", collect_queries)
    assert listed.status_code == 200 and len(listed.json()) == 4
    assert all(value["latest_execution"]["status"] == "CANCELLED" for value in listed.json())
    assert len([query for query in queries if "agent_runs" in query]) == 1
    assert len([query for query in queries if "conversation_configurations" in query]) == 1
    assert not any("platform_agent_versions" in query for query in queries)


def test_session_turn_authorization_idempotency_and_no_private_binding_leakage(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")
    assert (
        client.post(
            "/api/v1/sessions",
            headers=headers("reader"),
            json={"project_id": project_id, "agent_kind": "CRITIC"},
        ).status_code
        == 403
    )
    session_id = str(create_session(client, project_id, "contributor")["id"])
    profile_id = str(create_profile(client, "contributor")["id"])
    key = str(uuid4())
    accepted = send(client, session_id, profile_id, "contributor", client_request_id=key)
    assert accepted.status_code == 202
    assert (
        send(client, session_id, profile_id, "contributor", client_request_id=key).json()
        == accepted.json()
    )
    assert (
        send(
            client,
            session_id,
            profile_id,
            "contributor",
            client_request_id=key,
            content_md="Changed",
        ).status_code
        == 409
    )
    response = client.get(f"/api/v1/sessions/{session_id}", headers=headers("contributor"))
    assert response.json()["configuration"]["agent_version"] == 3
    assert "opaque_runtime_ref" not in response.text and "lease_owner" not in response.text
    assert response.json()["usage"] is None
    assert accepted.json()["item"]["author"]["type"] == "human"
    assert (
        send(client, session_id, profile_id, "contributor", author_user_id=str(uuid4())).status_code
        == 422
    )
    assert send(client, session_id, profile_id, "reader").status_code == 404


def test_session_and_run_history_are_private_to_the_current_requester(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")
    add_member(client, project_id, "same-email", "OWNER")
    session_id = str(create_session(client, project_id, "contributor")["id"])
    profile_id = str(create_profile(client, "contributor")["id"])
    run_id = send(client, session_id, profile_id, "contributor").json()["run"]["id"]
    for token in ("owner", "same-email", "reader", "outsider"):
        for path in (
            f"/api/v1/sessions/{session_id}",
            f"/api/v1/sessions/{session_id}/items",
            f"/api/v1/sessions/{session_id}/stream",
            f"/api/v1/sessions/{session_id}/child_sessions",
            f"/api/v1/runs/{run_id}",
        ):
            assert client.get(path, headers=headers(token)).status_code == 404
        assert interrupt(client, session_id, run_id, token).status_code == 404
        assert (
            client.patch(
                f"/api/v1/sessions/{session_id}",
                headers=headers(token),
                json={"archived": True},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/runs/{run_id}/resume",
                headers=headers(token),
                json={
                    "client_request_id": str(uuid4()),
                    "gateway_profile_id": profile_id,
                },
            ).status_code
            == 404
        )
    assert (
        client.get(
            "/api/v1/sessions",
            params={"project_id": project_id},
            headers=headers("reader"),
        ).json()
        == []
    )
    contributor_id = client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
    assert (
        client.delete(
            f"/api/v1/projects/{project_id}/members/{contributor_id}",
            headers=headers("owner"),
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/sessions/{session_id}/stream",
            headers={**headers("contributor"), "Last-Event-ID": "1:1"},
        ).status_code
        == 404
    )


def test_cancel_resume_and_committed_cursor_sse_reconnect(client: TestClient) -> None:
    project_id = str(create_project(client)["id"])
    profile_id = str(create_profile(client, "owner")["id"])
    session_id = str(create_session(client, project_id)["id"])
    run_id = send(client, session_id, profile_id).json()["run"]["id"]
    cancelled = interrupt(client, session_id, run_id)
    assert cancelled.status_code == 202 and cancelled.json()["run"]["status"] == "CANCELLED"
    assert interrupt(client, session_id, run_id).json() == cancelled.json()
    assert (
        client.patch(
            f"/api/v1/sessions/{session_id}",
            headers=headers("owner"),
            json={"archived": True},
        ).status_code
        == 200
    )
    events = client.get(f"/api/v1/sessions/{session_id}/stream", headers=headers("owner"))
    assert events.status_code == 200
    assert "id: 1:1\n" in events.text and "id: 1:2\n" in events.text
    assert "runtime" not in events.text.casefold()
    replay = client.get(
        f"/api/v1/sessions/{session_id}/stream",
        headers={**headers("owner"), "Last-Event-ID": "1:1"},
    )
    assert "id: 1:1\n" not in replay.text and "id: 1:2\n" in replay.text
    assert (
        client.get(
            f"/api/v1/sessions/{session_id}/stream",
            headers={**headers("owner"), "Last-Event-ID": "invalid"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/sessions/{session_id}",
            headers=headers("owner"),
            json={"archived": False},
        ).status_code
        == 200
    )
    body = {"client_request_id": str(uuid4()), "gateway_profile_id": profile_id}
    resumed = client.post(f"/api/v1/runs/{run_id}/resume", headers=headers("owner"), json=body)
    assert resumed.status_code == 202
    assert (
        client.post(f"/api/v1/runs/{run_id}/resume", headers=headers("owner"), json=body).json()[
            "id"
        ]
        == resumed.json()["id"]
    )
    assert resumed.json()["parent_run_id"] == run_id
    assert (
        client.get(f"/api/v1/sessions/{session_id}", headers=headers("owner")).json()[
            "latest_execution"
        ]["id"]
        == resumed.json()["id"]
    )


def test_only_creator_archives_private_session(client: TestClient) -> None:
    project_id = str(create_project(client)["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    session_id = str(create_session(client, project_id)["id"])
    assert (
        client.patch(
            f"/api/v1/sessions/{session_id}",
            headers=headers("contributor"),
            json={"archived": True},
        ).status_code
        == 404
    )
    archived = client.patch(
        f"/api/v1/sessions/{session_id}",
        headers=headers("owner"),
        json={"archived": True, "title": "Saved investigation"},
    )
    assert archived.status_code == 200 and archived.json()["status"] == "archived"
    assert archived.json()["title"] == "Saved investigation"
    assert not archived.json()["capabilities"]["can_send"]
    response = send(client, session_id, str(create_profile(client, "owner")["id"]))
    assert (
        response.status_code == 409 and response.json()["error"]["code"] == "session_state_conflict"
    )
    assert (
        client.get(
            "/api/v1/sessions",
            params={"project_id": project_id, "archived": False},
            headers=headers("owner"),
        ).json()
        == []
    )


def test_project_archive_atomically_stops_queued_agent_work(client: TestClient) -> None:
    project_id = str(create_project(client)["id"])
    session_id = str(create_session(client, project_id)["id"])
    run_id = send(client, session_id, str(create_profile(client, "owner")["id"])).json()["run"][
        "id"
    ]
    assert (
        client.patch(
            f"/api/v1/projects/{project_id}",
            headers=headers("owner"),
            json={"archived": True},
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/runs/{run_id}", headers=headers("owner")).json()["status"]
        == "CANCELLED"
    )
    assert (
        client.get(f"/api/v1/sessions/{session_id}", headers=headers("owner")).json()["status"]
        == "archived"
    )


def test_retired_session_routes_have_no_compatibility_api(client: TestClient) -> None:
    for path in (
        "/api/v1/agent-sessions",
        f"/api/v1/agent-runs/{uuid4()}",
        "/api/v1/chat/conversations",
    ):
        assert client.get(path, headers=headers("owner")).status_code == 404
    paths = cast(FastAPI, client.app).openapi()["paths"]
    assert not any(
        path.startswith(
            (
                "/api/v1/agent-sessions",
                "/api/v1/agent-runs",
                "/api/v1/chat/conversations",
            )
        )
        for path in paths
    )


def test_message_receipt_replays_after_archival_without_new_execution(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    session_id = str(create_session(client, project_id)["id"])
    profile_id = str(create_profile(client, "owner")["id"])
    request_id = str(uuid4())
    accepted = send(client, session_id, profile_id, client_request_id=request_id)
    assert accepted.status_code == 202
    archived = client.patch(
        f"/api/v1/sessions/{session_id}",
        headers=headers("owner"),
        json={"archived": True},
    )
    assert archived.status_code == 200
    replay = send(client, session_id, profile_id, client_request_id=request_id)
    assert replay.status_code == 202 and replay.json() == accepted.json()
    changed = send(
        client,
        session_id,
        profile_id,
        client_request_id=request_id,
        content_md="Different request",
    )
    assert changed.status_code == 409
    assert send(client, session_id, profile_id).status_code == 409
    run = client.get(f"/api/v1/runs/{accepted.json()['run']['id']}", headers=headers("owner"))
    assert run.json()["status"] == "CANCELLED"
    runs = client.get(f"/api/v1/sessions/{session_id}/runs", headers=headers("owner"))
    assert len(runs.json()) == 1

from __future__ import annotations

from typing import cast
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_workspace(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/workspaces",
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
        f"/api/v1/workspaces/{project_id}/members",
        headers=headers("owner"),
        json={"user_id": user["id"], "role": role},
    )
    assert response.status_code == 201, response.text


def create_session(client: TestClient, project_id: str, token: str = "owner") -> dict[str, object]:
    response = client.post(
        "/api/v1/agent-sessions",
        headers=headers(token),
        json={"workspace_id": project_id, "agent_kind": "RESEARCHER", "title": "Main thread"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_session_list_orders_by_latest_activity(client: TestClient) -> None:
    project = create_workspace(client)
    project_id = str(project["id"])
    older = create_session(client, project_id)
    newer = create_session(client, project_id)
    assert older["latest_run"] is None
    profile = create_profile(client, "owner")

    queued = client.post(
        f"/api/v1/agent-sessions/{older['id']}/messages",
        headers=headers("owner"),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "Resume the older investigation.",
            "gateway_profile_id": profile["id"],
        },
    )
    assert queued.status_code == 202, queued.text

    listed = client.get(
        f"/api/v1/agent-sessions?workspace_id={project_id}", headers=headers("owner")
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [older["id"], newer["id"]]
    assert listed.json()[0]["latest_run"] == {
        "id": queued.json()["run"]["id"],
        "status": "QUEUED",
        "cancel_requested_at": None,
    }
    assert listed.json()[1]["latest_run"] is None


def test_session_run_summaries_are_batched(client: TestClient) -> None:
    project_id = str(create_workspace(client)["id"])
    profile = create_profile(client, "owner")
    for _ in range(4):
        agent_session = create_session(client, project_id)
        response = client.post(
            f"/api/v1/agent-sessions/{agent_session['id']}/messages",
            headers=headers("owner"),
            json={
                "client_request_id": str(uuid4()),
                "content_md": "Investigate.",
                "gateway_profile_id": profile["id"],
            },
        )
        assert response.status_code == 202
        assert (
            client.post(
                f"/api/v1/agent-runs/{response.json()['run']['id']}/cancel",
                headers=headers("owner"),
            ).status_code
            == 202
        )

    queries: list[str] = []

    def collect_queries(*args: object) -> None:
        queries.append(str(args[2]))

    engine = cast(FastAPI, client.app).state.engine
    event.listen(engine, "before_cursor_execute", collect_queries)
    try:
        listed = client.get(
            f"/api/v1/agent-sessions?workspace_id={project_id}", headers=headers("owner")
        )
    finally:
        event.remove(engine, "before_cursor_execute", collect_queries)
    assert listed.status_code == 200
    assert len(listed.json()) == 4
    assert all(item["latest_run"]["status"] == "CANCELLED" for item in listed.json())
    assert len([query for query in queries if "agent_runs" in query]) == 1
    assert len([query for query in queries if "platform_agent_versions" in query]) == 1


def test_session_turn_authorization_idempotency_and_no_private_binding_leakage(
    client: TestClient,
) -> None:
    project = create_workspace(client)
    project_id = str(project["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")
    profile = create_profile(client, "contributor")

    agents = client.get("/api/v1/platform-agents", headers=headers("owner"))
    assert agents.status_code == 200
    assert {item["agent_kind"] for item in agents.json()} == {"RESEARCHER", "CRITIC"}

    assert (
        client.post(
            "/api/v1/agent-sessions",
            headers=headers("reader"),
            json={"workspace_id": project_id, "agent_kind": "CRITIC"},
        ).status_code
        == 403
    )
    agent_session = create_session(client, project_id, "contributor")
    session_id = str(agent_session["id"])
    assert "opaque_runtime_ref" not in str(agent_session)
    assert (
        client.get(f"/api/v1/agent-sessions/{session_id}", headers=headers("outsider")).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/agent-sessions/{session_id}", headers=headers("reader")).status_code
        == 403
    )

    request_id = str(uuid4())
    turn_body = {
        "client_request_id": request_id,
        "content_md": "Investigate the induction step.",
        "gateway_profile_id": profile["id"],
    }
    queued = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        headers=headers("contributor"),
        json=turn_body,
    )
    assert queued.status_code == 202, queued.text
    replay = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        headers=headers("contributor"),
        json=turn_body,
    )
    assert replay.status_code == 202
    assert replay.json() == queued.json()
    changed = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        headers=headers("contributor"),
        json={**turn_body, "content_md": "Different request"},
    )
    assert changed.status_code == 409
    assert (
        client.post(
            f"/api/v1/agent-sessions/{session_id}/messages",
            headers=headers("reader"),
            json={**turn_body, "client_request_id": str(uuid4())},
        ).status_code
        == 403
    )

    messages = client.get(
        f"/api/v1/agent-sessions/{session_id}/messages", headers=headers("reader")
    )
    assert messages.status_code == 403
    run = queued.json()["run"]
    assert "gateway_profile_id" not in run
    assert "gateway_model_id" not in run
    assert "lease_owner" not in run


def test_session_and_run_history_are_private_to_the_current_requester(client: TestClient) -> None:
    project_id = str(create_workspace(client)["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "same-email", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")
    profile = create_profile(client, "contributor")
    agent_session = create_session(client, project_id, "contributor")
    session_id = str(agent_session["id"])
    queued = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        headers=headers("contributor"),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "Private agent turn.",
            "gateway_profile_id": profile["id"],
        },
    )
    assert queued.status_code == 202
    run_id = queued.json()["run"]["id"]

    listed_own = client.get(
        f"/api/v1/agent-sessions?workspace_id={project_id}", headers=headers("contributor")
    )
    assert listed_own.status_code == 200
    assert [item["id"] for item in listed_own.json()] == [agent_session["id"]]
    assert (
        client.get(
            f"/api/v1/agent-sessions/{session_id}", headers=headers("contributor")
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/agent-sessions/{session_id}/messages", headers=headers("contributor")
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/agent-runs/{run_id}", headers=headers("contributor")).status_code
        == 200
    )

    for token in ("owner", "same-email"):
        listed = client.get(
            f"/api/v1/agent-sessions?workspace_id={project_id}", headers=headers(token)
        )
        assert listed.status_code == 200
        assert listed.json() == []
        for method, path, body in (
            ("get", f"/api/v1/agent-sessions/{session_id}", None),
            ("get", f"/api/v1/agent-sessions/{session_id}/messages", None),
            (
                "post",
                f"/api/v1/agent-sessions/{session_id}/messages",
                {
                    "client_request_id": str(uuid4()),
                    "content_md": "Not this member's chat.",
                    "gateway_profile_id": profile["id"],
                },
            ),
            ("post", f"/api/v1/agent-sessions/{session_id}/archive", None),
            ("get", f"/api/v1/agent-runs/{run_id}", None),
            ("post", f"/api/v1/agent-runs/{run_id}/cancel", None),
            (
                "post",
                f"/api/v1/agent-runs/{run_id}/resume",
                {
                    "client_request_id": str(uuid4()),
                    "gateway_profile_id": profile["id"],
                },
            ),
        ):
            if body is None:
                response = getattr(client, method)(path, headers=headers(token))
            else:
                response = client.post(path, headers=headers(token), json=body)
            assert response.status_code == 404, response.text

    for path in (
        f"/api/v1/agent-sessions?workspace_id={project_id}",
        f"/api/v1/agent-sessions/{session_id}",
        f"/api/v1/agent-sessions/{session_id}/messages",
        f"/api/v1/agent-runs/{run_id}",
        f"/api/v1/agent-runs/{run_id}/events",
        f"/api/v1/agent-sessions/{session_id}/events",
    ):
        assert client.get(path, headers=headers("reader")).status_code == 403

    assert (
        client.post(
            f"/api/v1/agent-runs/{run_id}/cancel", headers=headers("contributor")
        ).status_code
        == 202
    )
    for token in ("owner", "same-email"):
        assert (
            client.get(f"/api/v1/agent-runs/{run_id}/events", headers=headers(token)).status_code
            == 404
        )
    assert (
        client.get(
            f"/api/v1/agent-runs/{run_id}/events", headers=headers("contributor")
        ).status_code
        == 200
    )

    assert (
        client.post(
            f"/api/v1/agent-sessions/{session_id}/archive", headers=headers("contributor")
        ).status_code
        == 200
    )
    for token in ("owner", "same-email"):
        assert (
            client.get(
                f"/api/v1/agent-sessions/{session_id}/events", headers=headers(token)
            ).status_code
            == 404
        )
    assert (
        client.get(
            f"/api/v1/agent-sessions/{session_id}/events", headers=headers("contributor")
        ).status_code
        == 200
    )

    contributor_id = client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
    assert (
        client.delete(
            f"/api/v1/workspaces/{project_id}/members/{contributor_id}", headers=headers("owner")
        ).status_code
        == 204
    )
    # A reconnect with the old cursor must recheck current membership rather
    # than relying on authorization captured when the stream was opened.
    for path in (
        f"/api/v1/agent-sessions?workspace_id={project_id}",
        f"/api/v1/agent-sessions/{session_id}",
        f"/api/v1/agent-sessions/{session_id}/messages",
        f"/api/v1/agent-runs/{run_id}",
        f"/api/v1/agent-runs/{run_id}/events",
        f"/api/v1/agent-sessions/{session_id}/events",
    ):
        response = client.get(
            path,
            headers={**headers("contributor"), "Last-Event-ID": "1"},
        )
        assert response.status_code == 404


def test_cancel_resume_and_committed_cursor_sse_reconnect(client: TestClient) -> None:
    project_id = str(create_workspace(client)["id"])
    profile = create_profile(client, "owner")
    agent_session = create_session(client, project_id)
    session_id = str(agent_session["id"])
    queued = client.post(
        f"/api/v1/agent-sessions/{session_id}/messages",
        headers=headers("owner"),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "Try this route.",
            "gateway_profile_id": profile["id"],
        },
    ).json()
    run_id = queued["run"]["id"]

    cancelled = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=headers("owner"))
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "CANCELLED"
    cancelled_summary = client.get(
        f"/api/v1/agent-sessions/{session_id}", headers=headers("owner")
    ).json()["latest_run"]
    stored_run = client.get(f"/api/v1/agent-runs/{run_id}", headers=headers("owner")).json()
    assert cancelled_summary == {
        "id": run_id,
        "status": "CANCELLED",
        "cancel_requested_at": stored_run["cancel_requested_at"],
    }
    assert (
        client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=headers("owner")).json()[
            "status"
        ]
        == "CANCELLED"
    )

    events = client.get(f"/api/v1/agent-runs/{run_id}/events", headers=headers("owner"))
    assert events.status_code == 200
    assert "id: 1\n" in events.text
    assert "id: 2\n" in events.text
    assert "runtime" not in events.text.casefold()
    replay = client.get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={**headers("owner"), "Last-Event-ID": "1"},
    )
    assert "id: 1\n" not in replay.text
    assert "id: 2\n" in replay.text
    assert (
        client.get(
            f"/api/v1/agent-runs/{run_id}/events",
            headers={**headers("owner"), "Last-Event-ID": "invalid"},
        ).status_code
        == 422
    )

    resume_id = str(uuid4())
    resumed = client.post(
        f"/api/v1/agent-runs/{run_id}/resume",
        headers=headers("owner"),
        json={"client_request_id": resume_id, "gateway_profile_id": profile["id"]},
    )
    assert resumed.status_code == 202
    replayed_resume = client.post(
        f"/api/v1/agent-runs/{run_id}/resume",
        headers=headers("owner"),
        json={"client_request_id": resume_id, "gateway_profile_id": profile["id"]},
    )
    assert replayed_resume.json()["id"] == resumed.json()["id"]
    assert resumed.json()["parent_run_id"] == run_id
    latest = client.get(f"/api/v1/agent-sessions/{session_id}", headers=headers("owner")).json()[
        "latest_run"
    ]
    assert latest == {
        "id": resumed.json()["id"],
        "status": "QUEUED",
        "cancel_requested_at": None,
    }


def test_only_creator_archives_private_session(client: TestClient) -> None:
    project_id = str(create_workspace(client)["id"])
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    agent_session = create_session(client, project_id)
    session_id = str(agent_session["id"])
    assert (
        client.post(
            f"/api/v1/agent-sessions/{session_id}/archive",
            headers=headers("contributor"),
        ).status_code
        == 404
    )
    archived = client.post(f"/api/v1/agent-sessions/{session_id}/archive", headers=headers("owner"))
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"


def test_project_archive_atomically_stops_queued_agent_work(client: TestClient) -> None:
    project_id = str(create_workspace(client)["id"])
    profile = create_profile(client, "owner")
    agent_session = create_session(client, project_id)
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=headers("owner"),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "This must not run after archive.",
            "gateway_profile_id": profile["id"],
        },
    ).json()

    archived = client.patch(
        f"/api/v1/workspaces/{project_id}",
        headers=headers("owner"),
        json={"archived": True},
    )
    assert archived.status_code == 200
    run = client.get(f"/api/v1/agent-runs/{queued['run']['id']}", headers=headers("owner"))
    assert run.json()["status"] == "CANCELLED"
    stored_session = client.get(
        f"/api/v1/agent-sessions/{agent_session['id']}", headers=headers("owner")
    )
    assert stored_session.json()["status"] == "ARCHIVED"

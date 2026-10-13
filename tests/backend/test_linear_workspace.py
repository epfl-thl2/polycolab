"""Real Yjs + SQLite API coverage for the linear filesystem boundary."""

import base64
import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_hosted_scheduler import (
    hosted_client as hosted_client,
)
from test_hosted_scheduler import (
    scheduler_pg_schema as scheduler_pg_schema,
)
from test_sessions_api import add_member, headers


@pytest.fixture(scope="module")
def collaboration_url() -> Iterator[str]:
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = "polycolab-local-collaboration-token-change-in-production"
    process = subprocess.Popen(
        ["node", "--experimental-strip-types", "src/server.ts"],
        cwd=root / "src/collaboration",
        env={
            **os.environ,
            "COLLABORATION_TOKEN": token,
            "COLLABORATION_PORT": str(port),
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        with httpx.Client(trust_env=False) as http:
            for _ in range(100):
                if process.poll() is not None:
                    assert process.stderr is not None
                    raise RuntimeError(process.stderr.read().decode())
                try:
                    if http.get(url + "/health/live").is_success:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("collaboration service did not become ready")
        yield url
    finally:
        process.terminate()
        process.communicate(timeout=10)


@pytest.fixture
def linear(
    hosted_client: TestClient, tmp_path: Path, collaboration_url: str
) -> tuple[TestClient, str, str]:
    client = hosted_client
    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repositories"
    app.state.settings.collaboration_url = collaboration_url
    app.state.settings.feature_agent_execution_enabled = True
    result = client.post(
        "/api/v1/projects",
        headers=headers("owner"),
        json={"name": "Live proof", "workspace_mode": "linear"},
    )
    assert result.status_code == 201, result.text
    project = result.json()["id"]
    root = f"/api/v1/projects/{project}/linear"
    assert client.get(root, headers=headers("owner")).status_code == 200
    return client, project, root


def write(
    client: TestClient,
    root: str,
    commands: list[dict[str, Any]],
    sequence: int | None = 0,
    epoch: int = 1,
    key: str | None = None,
    user: str = "owner",
) -> httpx.Response:
    response = client.post(
        root + "/changes",
        headers={**headers(user), "Idempotency-Key": key or str(uuid4())},
        json={"epoch": epoch, "expected_sequence": sequence, "commands": commands},
    )
    return cast(httpx.Response, response)


def create_file(
    path: str = "proof.lean", text: str = "theorem example := trivial"
) -> dict[str, Any]:
    return {
        "kind": "create",
        "file_id": str(uuid4()),
        "path": path,
        "content_base64": base64.b64encode(text.encode()).decode(),
    }


def test_saved_history_retry_and_authority(linear: tuple[TestClient, str, str]) -> None:
    client, project, root = linear
    command = create_file()
    result = write(client, root, [command], key="create")
    assert result.status_code == 200, result.text
    assert result.json()["sequence"] == 1
    assert write(client, root, [command], key="create").json() == result.json()
    document = client.get(root + "/files/" + command["file_id"], headers=headers("owner")).json()
    assert document["document"]
    assert base64.b64decode(document["content_base64"]).decode() == "theorem example := trivial"
    assert write(client, root, [create_file("other.lean")]).status_code == 409
    assert write(client, root, [create_file("../escape")], sequence=1).status_code == 422
    add_member(client, project, "reader", "READ_ONLY")
    assert client.get(root, headers=headers("reader")).json()["writable"] is False
    assert write(client, root, [create_file()], sequence=1, user="reader").status_code == 403
    assert client.get(root, headers=headers("outsider")).status_code == 404
    assert len(client.get(root + "/history", headers=headers("owner")).json()) == 1


def test_restore_is_owner_only_and_fences_old_documents(
    linear: tuple[TestClient, str, str],
) -> None:
    client, project, root = linear
    command = create_file()
    assert write(client, root, [command]).status_code == 200
    checkpoint = client.post(
        root + "/checkpoints",
        headers=headers("owner"),
        json={"id": str(uuid4()), "title": "First proof"},
    ).json()
    assert (
        write(
            client,
            root,
            [{"kind": "delete", "file_id": command["file_id"]}],
            sequence=1,
        ).status_code
        == 200
    )
    add_member(client, project, "contributor", "CONTRIBUTOR")
    body = {"epoch": 1, "sequence": 2, "checkpoint_id": checkpoint["id"]}
    assert (
        client.post(
            root + "/restore",
            headers={**headers("contributor"), "Idempotency-Key": "restore"},
            json=body,
        ).status_code
        == 403
    )
    restored = client.post(
        root + "/restore",
        headers={**headers("owner"), "Idempotency-Key": "restore"},
        json=body,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["epoch"] == 2
    assert (
        client.post(
            root + "/restore",
            headers={**headers("owner"), "Idempotency-Key": "restore"},
            json=body,
        ).json()
        == restored.json()
    )
    assert write(client, root, [create_file("old.txt")], sequence=3).status_code == 409
    state = client.get(root, headers=headers("owner")).json()
    assert state["files"][0]["path"] == "proof.lean"
    assert state["files"][0]["id"] != command["file_id"]


def test_structural_batch_is_atomic(linear: tuple[TestClient, str, str]) -> None:
    client, _, root = linear
    first, second = create_file("a.txt"), create_file("b.txt")
    assert write(client, root, [first, second]).status_code == 200
    result = write(
        client,
        root,
        [
            {"kind": "delete", "file_id": first["file_id"]},
            {"kind": "rename", "file_id": second["file_id"], "path": "../bad"},
        ],
        sequence=1,
    )
    assert result.status_code == 422
    state = client.get(root, headers=headers("owner")).json()
    assert state["sequence"] == 1
    assert sorted(f["path"] for f in state["files"]) == ["a.txt", "b.txt"]


def test_shared_chat_read_access_and_unshare(linear: tuple[TestClient, str, str]) -> None:
    from test_sessions_api import create_session

    client, project, root = linear
    add_member(client, project, "reader", "READ_ONLY")
    add_member(client, project, "contributor", "CONTRIBUTOR")
    chat = create_session(client, project)
    url = f"/api/v1/agent-sessions/{chat['id']}"
    listing = f"/api/v1/agent-sessions?project_id={project}"
    assert client.get(listing, headers=headers("reader")).json() == []
    assert client.get(url, headers=headers("contributor")).status_code == 404
    shared = client.patch(url + "/visibility", headers=headers("owner"), json={"is_shared": True})
    assert shared.status_code == 200, shared.text
    assert [item["id"] for item in client.get(listing, headers=headers("reader")).json()] == [
        chat["id"]
    ]
    for viewer in ("reader", "contributor"):
        response = client.get(url, headers=headers(viewer))
        assert response.status_code == 200, response.text
        assert response.json()["can_control"] is False
        assert response.json()["system_prompt"] is None
        assert client.get(url + "/messages", headers=headers(viewer)).status_code == 200
        assert client.patch(
            url + "/visibility", headers=headers(viewer), json={"is_shared": False}
        ).status_code in (403, 404)
    assert client.get(url, headers=headers("outsider")).status_code == 404
    assert (
        client.patch(
            url + "/visibility", headers=headers("owner"), json={"is_shared": False}
        ).status_code
        == 200
    )
    assert client.get(url, headers=headers("contributor")).status_code == 404
    assert client.get(listing, headers=headers("reader")).json() == []


def test_conversion_preserves_saved_overlay_and_freezes_git(
    client: TestClient, tmp_path: Path, collaboration_url: str
) -> None:
    from test_sessions_api import create_project

    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repos"
    app.state.settings.collaboration_url = collaboration_url
    app.state.settings.feature_agent_execution_enabled = True
    project = create_project(client)["id"]
    base = f"/api/v1/projects/{project}"
    tree = client.get(base + "/worktrees", headers=headers("owner")).json()[0]
    saved = client.post(
        base + f"/worktrees/{tree['id']}/save",
        headers={**headers("owner"), "Idempotency-Key": "saved-overlay"},
        json={
            "expected_revision": tree["revision"],
            "changes": [{"path": "notes.txt", "content_base64": "c2F2ZWQ="}],
        },
    )
    assert saved.status_code == 200, saved.text
    preview = client.get(
        base + "/linear/conversion-preview",
        params={"worktree_id": tree["id"]},
        headers=headers("owner"),
    )
    assert preview.json()["saved_changes"] is True
    body = {"worktree_id": tree["id"], "revision": preview.json()["revision"]}
    auth = {**headers("owner"), "Idempotency-Key": "convert"}
    converted = client.post(base + "/linear/convert", headers=auth, json=body)
    assert converted.status_code == 200, converted.text
    assert converted.json()["files"][0]["path"] == "notes.txt"
    assert client.post(base + "/linear/convert", headers=auth, json=body).json() == converted.json()
    archive = client.get(base + f"/worktrees/{tree['id']}", headers=headers("owner"))
    assert archive.json()["head_commit"] == tree["head_commit"]
    assert archive.json()["writable"] is False
    assert (
        client.post(
            base + f"/worktrees/{tree['id']}/save",
            headers=auth,
            json={
                "expected_revision": saved.json()["revision"],
                "changes": [{"path": "overwrite.txt", "content_base64": "eA=="}],
            },
        ).status_code
        == 409
    )


def test_websocket_ack_replay_and_revoked_write(
    linear: tuple[TestClient, str, str], collaboration_url: str
) -> None:
    client, project, root = linear
    command = create_file(text="first\nsecond\n")
    assert write(client, root, [command]).status_code == 200
    add_member(client, project, "contributor", "CONTRIBUTOR")
    app = cast(FastAPI, client.app)
    origin = str(app.state.settings.allowed_origins[0]).rstrip("/")
    doc = client.get(root + "/files/" + command["file_id"], headers=headers("owner")).json()
    from uuid import UUID

    from polycolab.projects.linear_service import CollaborationClient

    engine = CollaborationClient(
        collaboration_url, app.state.settings.collaboration_token.get_secret_value()
    )
    update = engine.prepare(
        UUID(project), [{"state": doc["document"], "text": "first\nsecond\nthird\n"}]
    )[0]["update"]
    body = {
        "epoch": 1,
        "commands": [{"kind": "update", "file_id": command["file_id"], "update": update}],
    }
    with client.websocket_connect(root + "/events", headers={"origin": origin}) as socket:
        socket.send_json({"version": 1, "after": 1, "authorization": "Bearer contributor"})

        def receive(kind: str) -> dict[str, Any]:
            for _ in range(20):
                message = socket.receive_json()
                if message["kind"] == kind:
                    return cast(dict[str, Any], message)
            raise AssertionError("Missing " + kind)

        socket.send_json({"kind": "update", "request_id": "socket-save", "body": body})
        receipt = receive("ack")
        assert receipt["sequence"] == 2
        socket.send_json({"kind": "update", "request_id": "socket-save", "body": body})
        assert receive("ack")["sequence"] == 2
        contributor = client.get("/api/v1/users/me", headers=headers("contributor")).json()
        assert (
            client.delete(
                f"/api/v1/projects/{project}/members/{contributor['id']}", headers=headers("owner")
            ).status_code
            == 204
        )
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            while True:
                socket.receive_json()
    current = client.get(root + "/files/" + command["file_id"], headers=headers("owner")).json()
    assert base64.b64decode(current["content_base64"]) == b"first\nsecond\nthird\n"
    assert len(client.get(root + "/history", headers=headers("owner")).json()) == 2


def test_missing_repository_blocks_writes_without_reinitializing(
    linear: tuple[TestClient, str, str],
) -> None:
    client, project, root = linear
    assert write(client, root, [create_file()]).status_code == 200
    app = cast(FastAPI, client.app)
    repository = app.state.settings.project_repository_directory / f"{project}.git"
    repository.rename(repository.with_suffix(".missing"))
    response = write(client, root, [create_file("later.txt")], sequence=1)
    assert response.status_code == 503
    assert not repository.exists()
    assert client.get(root, headers=headers("owner")).json()["sequence"] == 1


def test_accepted_change_survives_checkpoint_failure(
    linear: tuple[TestClient, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from polycolab.entities.repositories import RepositoryError
    from polycolab.projects.linear_service import LinearService

    client, project, root = linear

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RepositoryError("repository_unavailable", 503)

    monkeypatch.setattr(LinearService, "checkpoint", unavailable)
    response = write(client, root, [create_file()], key="durable")
    assert response.status_code == 200, response.text
    assert client.get(root, headers=headers("owner")).json()["sequence"] == 1


def test_transient_collaboration_failure_allows_same_update_to_retry(
    linear: tuple[TestClient, str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.websockets import WebSocketDisconnect

    from polycolab.entities.repositories import RepositoryError
    from polycolab.projects.linear_service import CollaborationClient

    client, project, root = linear
    app = cast(FastAPI, client.app)
    origin = str(app.state.settings.allowed_origins[0]).rstrip("/")
    command = create_file()
    message = {
        "kind": "update",
        "request_id": "retry-after-outage",
        "body": {"epoch": 1, "expected_sequence": 0, "commands": [command]},
    }

    def unavailable(*args: object, **kwargs: object) -> None:
        raise RepositoryError("collaboration_unavailable", 503)

    with monkeypatch.context() as patch:
        patch.setattr(CollaborationClient, "prepare", unavailable)
        with client.websocket_connect(root + "/events", headers={"origin": origin}) as socket:
            socket.send_json({"version": 1, "after": 0, "authorization": "Bearer owner"})
            socket.send_json(message)
            with pytest.raises(WebSocketDisconnect) as disconnected:
                while True:
                    socket.receive_json()
            assert disconnected.value.code == 1013
    assert client.get(root, headers=headers("owner")).json()["sequence"] == 0
    with client.websocket_connect(root + "/events", headers={"origin": origin}) as socket:
        socket.send_json({"version": 1, "after": 0, "authorization": "Bearer owner"})
        socket.send_json(message)
        while True:
            receipt = socket.receive_json()
            if receipt["kind"] == "ack":
                assert receipt["sequence"] == 1
                break
    assert len(client.get(root + "/history", headers=headers("owner")).json()) == 1

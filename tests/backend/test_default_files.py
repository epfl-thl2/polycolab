"""Default projects store only current files and enforce member save authority."""

from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from test_sessions_api import add_member, headers


@pytest.fixture
def files(client: TestClient, tmp_path: Path) -> tuple[TestClient, str, Path]:
    app = cast(Any, client.app)
    app.state.settings.project_repository_directory = tmp_path
    response = client.post(
        "/api/v1/projects",
        headers=headers("owner"),
        json={
            "name": "Plain files",
            "visibility": "PRIVATE",
            "workspace_mode": "default",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["workspace_mode"] == "default"
    project_id = response.json()["id"]
    return (
        client,
        f"/api/v1/projects/{project_id}/files",
        tmp_path / f"{project_id}.files",
    )


def test_files_crud_conflicts_and_no_history(
    files: tuple[TestClient, str, Path],
) -> None:
    client, root, directory = files

    def command(**values: Any) -> Any:
        return client.post(root, headers=headers("owner"), json=values)

    first = command(action="write", path="notes/one.md", content="first")
    assert first.status_code == 200, first.text
    digest = first.json()["digest"]
    assert (directory / "notes/one.md").read_text() == "first"
    assert command(action="write", path="notes/one.md", content="clobber").status_code == 409
    second = command(action="write", path="notes/one.md", content="second", expected_digest=digest)
    assert second.status_code == 200
    assert command(action="delete", path="notes/one.md", expected_digest=digest).status_code == 409
    renamed = command(
        action="rename",
        path="notes/one.md",
        destination="two.md",
        expected_digest=second.json()["digest"],
    )
    assert renamed.status_code == 200
    assert not (directory / "notes/one.md").exists()
    assert command(action="read", path="two.md").json()["content"] == "second"
    assert (
        command(
            action="delete", path="two.md", expected_digest=renamed.json()["digest"]
        ).status_code
        == 200
    )
    assert client.get(root, headers=headers("owner")).json()["files"] == []
    assert {p.name for p in directory.parent.iterdir()} == {
        directory.name,
        directory.name + ".lock",
    }


def test_permissions_and_mode_isolation(files: tuple[TestClient, str, Path]) -> None:
    client, root, directory = files
    project_id = directory.name.removesuffix(".files")
    add_member(client, project_id, "reader", "READ_ONLY")
    assert client.get(root, headers=headers("reader")).json()["writable"] is False
    assert (
        client.post(
            root,
            headers=headers("reader"),
            json={"action": "write", "path": "a", "content": "x"},
        ).status_code
        == 403
    )
    assert client.get(root, headers=headers("outsider")).status_code == 404
    assert client.get(root).status_code == 401
    assert (
        client.get(root.replace("/files", "/linear"), headers=headers("owner")).status_code == 409
    )
    other = client.post(
        "/api/v1/projects",
        headers=headers("owner"),
        json={"name": "Git", "workspace_mode": "git"},
    ).json()["id"]
    assert (
        client.get(f"/api/v1/projects/{other}/files", headers=headers("owner")).status_code == 409
    )
    client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers("owner"),
        json={"archived": True},
    )
    assert client.post(
        root,
        headers=headers("owner"),
        json={"action": "write", "path": "a", "content": "x"},
    ).status_code in {403, 409}


@pytest.mark.parametrize(
    "path", ["../escape", "/absolute", "a/../../escape", ".git/config", "a\\b"]
)
def test_path_escape_rejected(files: tuple[TestClient, str, Path], path: str) -> None:
    client, root, _ = files
    assert (
        client.post(
            root,
            headers=headers("owner"),
            json={"action": "write", "path": path, "content": "x"},
        ).status_code
        == 422
    )


def test_symlinks_and_quotas(files: tuple[TestClient, str, Path]) -> None:
    client, root, directory = files
    assert client.get(root, headers=headers("owner")).status_code == 200
    outside = directory.parent / "outside"
    outside.mkdir()
    (directory / "link").symlink_to(outside, target_is_directory=True)
    assert (
        client.post(
            root,
            headers=headers("owner"),
            json={"action": "write", "path": "link/escape", "content": "x"},
        ).status_code
        == 422
    )
    assert not (outside / "escape").exists()
    (directory / "link").unlink()
    cast(Any, client.app).state.settings.project_repository_max_bytes = 3
    assert (
        client.post(
            root,
            headers=headers("owner"),
            json={"action": "write", "path": "large", "content": "long"},
        ).status_code
        == 413
    )
    assert not (directory / "large").exists()


def test_agent_tool_uses_current_directory_without_repository(
    client: TestClient, tmp_path: Path
) -> None:
    from test_hosted_artifacts import WORKER
    from test_hosted_scheduler import new_hosted

    from polycolab.db.models import SqlAgentRun, SqlProject, SqlUser

    run_id = new_hosted(client)
    app = cast(Any, client.app)
    app.state.settings.project_repository_directory = tmp_path
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        project_id = str(run.project_id)
        db.get(SqlProject, run.project_id).workspace_mode = "default"
        db.get(SqlUser, run.requested_by_user_id).subject = "owner"
        db.commit()
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers=WORKER,
        json={"worker_id": "default-worker", "engine": "codex"},
    )
    assert claim.status_code == 200, claim.text
    assert "repository" not in claim.json()
    assert "project_files" in {t["function"]["name"] for t in claim.json()["tools"]}
    tool_headers = {
        "Authorization": "Bearer " + claim.json()["tool_capability"],
        "x-polycolab-tool-invocation": "default-write",
        "x-polycolab-source-event-cursor": "1",
    }
    result = client.post(
        "/internal/v1/tools/call",
        headers=tool_headers,
        json={
            "name": "project_files",
            "arguments": {
                "action": "write",
                "path": "agent.txt",
                "content": "Agent output",
            },
        },
    )
    assert result.status_code == 200, result.text
    assert (tmp_path / f"{project_id}.files" / "agent.txt").read_text() == "Agent output"
    assert not (tmp_path / f"{project_id}.git").exists()
    assert "content" not in result.json()
    partial = client.post(
        "/internal/v1/tools/call",
        headers=tool_headers,
        json={
            "name": "project_files",
            "arguments": {"action": "read", "path": "agent.txt", "limit": 5},
        },
    )
    assert partial.status_code == 200
    assert partial.json()["content"] == "Agent"
    assert partial.json()["next_offset"] == 5
    # Revocation must apply to an already issued capability.
    client.patch(
        f"/api/v1/projects/{project_id}",
        headers=headers("owner"),
        json={"archived": True},
    )
    denied = client.post(
        "/internal/v1/tools/call",
        headers=tool_headers,
        json={
            "name": "project_files",
            "arguments": {"action": "write", "path": "late.txt", "content": "late"},
        },
    )
    assert denied.status_code in {401, 403}
    assert not (tmp_path / f"{project_id}.files" / "late.txt").exists()


@pytest.mark.parametrize("client", ["file"], indirect=True)
def test_concurrent_saves_preserve_one_winner(
    files: tuple[TestClient, str, Path],
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    client, root, directory = files
    created = client.post(
        root,
        headers=headers("owner"),
        json={"action": "write", "path": "a", "content": "base"},
    ).json()

    def save(content: str) -> int:
        response = client.post(
            root,
            headers=headers("owner"),
            json={
                "action": "write",
                "path": "a",
                "content": content,
                "expected_digest": created["digest"],
            },
        )
        return int(response.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["one", "two"])) == [200, 409]
    assert (directory / "a").read_text() in {"one", "two"}

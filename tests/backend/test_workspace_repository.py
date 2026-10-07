from __future__ import annotations

import base64
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from polycolab.entities.repositories import RepositoryError
from polycolab.workspaces.git_storage import GitRepository

OWNER = {"Authorization": "Bearer owner"}


@pytest.fixture
def repository(client: TestClient, tmp_path: Path) -> tuple[TestClient, str]:
    cast(FastAPI, client.app).state.settings.workspace_repository_directory = tmp_path / "repos"
    response = client.post(
        "/api/v1/workspaces", headers=OWNER, json={"name": "Files", "visibility": "PUBLIC"}
    )
    assert response.status_code == 201, response.text
    return client, f"/api/v1/workspaces/{response.json()['id']}/repository"


def change(
    client: TestClient, url: str, head: str, path: str, text: str | None, key: str = "save"
) -> Response:
    return cast(
        Response,
        client.post(
            url + "/changes",
            headers={**OWNER, "Idempotency-Key": key},
            json={
                "expected_commit": head,
                "changes": [
                    {
                        "path": path,
                        "content_base64": base64.b64encode(text.encode()).decode()
                        if text is not None
                        else None,
                    }
                ],
            },
        ),
    )


def test_files_history_retry_and_stale_save(repository: tuple[TestClient, str]) -> None:
    client, url = repository
    initial = client.get(url, headers=OWNER)
    assert initial.status_code == 200, initial.text
    head = initial.json()["commit"]
    saved = change(client, url, head, "notes/idea.md", "First idea")
    assert saved.status_code == 200, saved.text
    commit = saved.json()["commit"]
    assert change(client, url, head, "notes/idea.md", "First idea").json()["commit"] == commit
    assert change(client, url, head, "notes/idea.md", "Different").status_code == 409
    assert change(client, url, head, "notes/idea.md", "Stale", "other").status_code == 409
    file = client.get(
        url + "/file", headers=OWNER, params={"commit": commit, "path": "notes/idea.md"}
    )
    assert base64.b64decode(file.json()["content_base64"]) == b"First idea"
    assert len(client.get(url + "/history", headers=OWNER).json()) == 2
    assert client.get(url, headers=OWNER).json()["files"][0]["path"] == "notes/idea.md"
    deleted = change(client, url, commit, "notes/idea.md", None, "delete")
    assert deleted.status_code == 200
    assert client.get(url, headers=OWNER).json()["files"] == []
    assert (
        client.get(
            url + "/file", headers=OWNER, params={"commit": commit, "path": "notes/idea.md"}
        ).status_code
        == 200
    )


def test_public_workspace_files_remain_member_only(repository: tuple[TestClient, str]) -> None:
    client, url = repository
    assert client.get(url).status_code == 401
    assert client.get(url, headers={"Authorization": "Bearer outsider"}).status_code == 404
    user = client.get("/api/v1/me", headers={"Authorization": "Bearer reader"}).json()
    added = client.post(
        url.removesuffix("/repository") + "/members",
        headers=OWNER,
        json={"user_id": user["user_id"], "role": "READ_ONLY"},
    )
    assert added.status_code == 201, added.text
    assert client.get(url, headers={"Authorization": "Bearer reader"}).json()["writable"] is False
    state = client.get(url, headers=OWNER).json()
    response = client.post(
        url + "/changes",
        headers={"Authorization": "Bearer reader", "Idempotency-Key": "read"},
        json={
            "expected_commit": state["commit"],
            "changes": [{"path": "x", "content_base64": "eA=="}],
        },
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "path", ["../secret", "/absolute", ".git/config", "x/.GIT/config", "a\\b", "x//y"]
)
def test_unsafe_paths_fail(repository: tuple[TestClient, str], path: str) -> None:
    client, url = repository
    head = client.get(url, headers=OWNER).json()["commit"]
    assert change(client, url, head, path, "bad").status_code == 422


def test_git_roundtrip_merge_and_conflict(tmp_path: Path) -> None:
    git = GitRepository(tmp_path, uuid4())
    branch = f"sessions/{uuid4()}"
    with git.locked():
        initial = git.head("main")
        first = git.commit_tree(
            git.changed_tree(initial, {"a.txt": b"base\n"}), [initial], "first", "human"
        )
        git.advance("main", initial, first)
        git.advance(branch, "0" * 40, first)
        left = git.commit_tree(
            git.changed_tree(first, {"a.txt": b"left\n"}), [first], "left", "human"
        )
        right = git.commit_tree(
            git.changed_tree(first, {"a.txt": b"right\n"}), [first], "right", "agent"
        )
        git.advance("main", first, left)
        git.advance(branch, first, right)
        _, conflicts = git.merge(left, right)
        assert conflicts == ["a.txt"]
        assert git.bundle(branch).startswith(b"# v2 git bundle")
    with GitRepository(tmp_path, UUID(git.path.name[:-4])).locked():
        assert git.read(left, "a.txt") == b"left\n"


def test_quota_and_path_collision(tmp_path: Path) -> None:
    git = GitRepository(tmp_path, uuid4(), quota=1024)
    with git.locked():
        with pytest.raises(RepositoryError, match="quota"):
            git.changed_tree(git.head("main"), {"a": b"data"})
    git.quota = 64 * 1024 * 1024
    with git.locked():
        with pytest.raises(RepositoryError, match="collision"):
            git.changed_tree(git.head("main"), {"a": b"x", "a/b": b"y"})


def test_bundle_restore_checkpoint_and_import(tmp_path: Path) -> None:
    from polycolab.execution import guest_repository

    git = GitRepository(tmp_path / "remote", uuid4())
    branch = f"sessions/{uuid4()}"
    with git.locked():
        head = git.head("main")
        commit = git.commit_tree(
            git.changed_tree(head, {"proofs/Main.lean": b"-- initial\n"}), [head], "seed", "human"
        )
        git.advance("main", head, commit)
        git.advance(branch, "0" * 40, commit)
        bundle = git.bundle(branch, commit=commit)
    inputs, outputs, work = tmp_path / "inputs", tmp_path / "outputs", tmp_path / "work"
    inputs.mkdir()
    outputs.mkdir()
    import json

    (inputs / "workspace.bundle").write_bytes(bundle)
    (inputs / "workspace.json").write_text(json.dumps({"branch": branch, "commit": commit}))
    metadata = guest_repository.checkout(inputs, work)
    assert metadata is not None
    (work / "proofs/Main.lean").write_text("-- agent work\n")
    # A subtask can use a linked worktree and integrate it before checkpointing.
    other = tmp_path / "subtask"
    guest_repository.git(work, "worktree", "add", "-b", "subtask", str(other))
    (other / "note.md").write_text("subtask result")
    guest_repository.git(other, "add", "note.md")
    import os
    import subprocess

    subprocess.run(
        ["git", "-C", str(other), "commit", "-m", "Subtask"],
        env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
        check=True,
        capture_output=True,
    )
    guest_repository.git(work, "merge", "--no-edit", "subtask")
    final = guest_repository.checkpoint(metadata, work, outputs)
    with git.locked():
        imported = git.import_bundle((outputs / "workspace.bundle").read_bytes(), branch, commit)
        assert imported == final
        git.advance(branch, commit, imported)
        assert git.read(imported, "proofs/Main.lean") == b"-- agent work\n"
        assert git.read(imported, "note.md") == b"subtask result"
        (inputs / "workspace.bundle").write_bytes(git.bundle(branch, commit=imported))
    (inputs / "workspace.json").write_text(json.dumps({"branch": branch, "commit": imported}))
    fresh = tmp_path / "fresh"
    guest_repository.checkout(inputs, fresh)
    assert (fresh / "note.md").read_text() == "subtask result"


def test_reconcile_saved_ref_after_sql_failure(
    repository: tuple[TestClient, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from polycolab.db.stores.repositories import SqlRepositoryStore

    client, url = repository
    head = client.get(url, headers=OWNER).json()["commit"]
    original = SqlRepositoryStore.complete

    def fail(self: SqlRepositoryStore, receipt_id: UUID) -> None:
        raise RuntimeError("simulated process loss")

    monkeypatch.setattr(SqlRepositoryStore, "complete", fail)
    assert change(client, url, head, "draft.md", "durable").status_code == 500
    monkeypatch.setattr(SqlRepositoryStore, "complete", original)
    response = change(client, url, head, "draft.md", "durable")
    assert response.status_code == 200, response.text
    assert len(client.get(url + "/history", headers=OWNER).json()) == 2


def test_missing_registered_volume_fails_closed(
    repository: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, url = repository
    assert client.get(url, headers=OWNER).status_code == 200
    cast(FastAPI, client.app).state.settings.workspace_repository_directory = (
        tmp_path / "empty-volume"
    )
    response = client.get(url, headers=OWNER)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "repository_storage_missing"


def test_merge_requires_current_heads_and_explicit_resolution(
    repository: tuple[TestClient, str],
) -> None:
    client, url = repository
    app = cast(FastAPI, client.app)
    head = client.get(url, headers=OWNER).json()["commit"]
    common = change(client, url, head, "note.md", "base\n").json()["commit"]
    branch = f"sessions/{uuid4()}"
    git = GitRepository(app.state.settings.workspace_repository_directory, UUID(url.split("/")[4]))
    with git.locked():
        incoming = git.commit_tree(
            git.changed_tree(common, {"note.md": b"agent\n"}), [common], "Agent", "agent"
        )
        git.advance(branch, "0" * 40, incoming)
    current = change(client, url, common, "note.md", "human\n", "human").json()["commit"]
    preview = client.get(url + "/merge", headers=OWNER, params={"source": branch}).json()
    assert [item["path"] for item in preview["conflicts"]] == ["note.md"]
    body = {"source": branch, "expected_target": current, "expected_source": incoming}
    headers = {**OWNER, "Idempotency-Key": "merge"}
    assert client.post(url + "/merge", headers=headers, json=body).status_code == 409
    assert (
        client.post(
            url + "/merge", headers=headers, json={**body, "expected_source": common}
        ).status_code
        == 409
    )
    resolved = client.post(
        url + "/merge",
        headers=headers,
        json={
            **body,
            "resolutions": [
                {"path": "note.md", "content_base64": base64.b64encode(b"resolved\n").decode()}
            ],
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert git.read(resolved.json()["commit"], "note.md") == b"resolved\n"

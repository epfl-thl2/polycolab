"""Real Git + SQLite API coverage for shared native working directories."""

from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_sessions_api import add_member, create_project, headers

from polycolab.projects.git_storage import GitRepository
from polycolab.projects.worktree_storage import WorktreeStorage


@pytest.fixture
def native(client: TestClient, tmp_path: Path) -> tuple[TestClient, str, GitRepository]:
    app = cast(FastAPI, client.app)
    app.state.settings.project_repository_directory = tmp_path / "repos"
    project_id = str(create_project(client)["id"])
    return client, project_id, GitRepository(tmp_path / "repos", UUID(project_id))


def test_save_commit_discard_and_remove(native: tuple[TestClient, str, GitRepository]) -> None:
    client, project, git = native
    root = f"/api/v1/projects/{project}/worktrees"
    auth = headers("owner")
    response = client.get(root, headers=auth)
    assert response.status_code == 200, response.text
    main = response.json()[0]
    assert main["branch"] == "main"
    create = {"client_request_id": str(uuid4()), "title": "Experiment", "branch": "experiment"}
    response = client.post(root, headers=auth, json=create)
    assert response.status_code == 201, response.text
    worktree = response.json()
    assert client.post(root, headers=auth, json=create).json() == worktree
    url = root + "/" + worktree["id"]
    with git.locked():
        assert WorktreeStorage(git).available(UUID(worktree["id"]), "experiment")
    body = {
        "expected_revision": worktree["revision"],
        "changes": [{"path": "notes.txt", "content_base64": "aGVsbG8="}],
    }
    retry = {**auth, "Idempotency-Key": "save-1"}
    response = client.post(url + "/save", headers=retry, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()["revision"]
    assert client.post(url + "/save", headers=retry, json=body).json()["revision"] == saved
    assert (
        client.post(
            url + "/save", headers={**auth, "Idempotency-Key": "stale"}, json=body
        ).status_code
        == 409
    )
    state = client.get(url, headers=auth).json()
    assert state["head_commit"] == worktree["head_commit"]
    assert state["changed_files"] == [{"path": "notes.txt", "status": "added"}]
    assert client.get(root + "/" + main["id"], headers=auth).json()["files"] == []
    assert (WorktreeStorage(git).path(UUID(worktree["id"])) / "notes.txt").read_text() == "hello"
    commit = client.post(
        url + "/commit",
        headers={**auth, "Idempotency-Key": "commit-1"},
        json={"expected_revision": saved, "message": "Add notes"},
    )
    assert commit.status_code == 200, commit.text
    state = client.get(url, headers=auth).json()
    assert state["head_commit"] != worktree["head_commit"]
    assert state["changed_files"] == []
    body["expected_revision"] = state["revision"]
    body["changes"][0]["content_base64"] = "dXBkYXRlZA=="
    save2 = client.post(
        url + "/save", headers={**auth, "Idempotency-Key": "save-2"}, json=body
    ).json()
    denied = client.post(
        url + "/remove",
        headers={**auth, "Idempotency-Key": "remove"},
        json={"expected_revision": save2["revision"]},
    )
    assert denied.status_code == 409
    discard = client.post(
        url + "/discard",
        headers={**auth, "Idempotency-Key": "discard"},
        json={"expected_revision": save2["revision"]},
    )
    assert discard.status_code == 200, discard.text
    assert (
        client.post(
            url + "/remove",
            headers={**auth, "Idempotency-Key": "remove"},
            json={"expected_revision": discard.json()["revision"]},
        ).json()["lifecycle"]
        == "removed"
    )
    assert not WorktreeStorage(git).path(UUID(worktree["id"])).exists()
    assert client.post(url + "/restore", headers=auth).json()["lifecycle"] == "active"
    assert (WorktreeStorage(git).path(UUID(worktree["id"])) / "notes.txt").read_text() == "hello"
    add_member(client, project, "reader", "READ_ONLY")
    assert client.get(url, headers=headers("reader")).json()["writable"] is False
    assert (
        client.post(
            url + "/save", headers={**headers("reader"), "Idempotency-Key": "denied"}, json=body
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/projects/{project}/repository/changes",
            headers=retry,
            json={
                "branch": "experiment",
                "expected_commit": state["head_commit"],
                "changes": body["changes"],
            },
        ).status_code
        == 409
    )


def test_durable_recovery_keeps_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = GitRepository(tmp_path, uuid4())
    identifier = uuid4()
    files = WorktreeStorage(git)
    with git.locked():
        files.initialize(identifier, "main")
        head = git.head("main")
        previous = files.revision(identifier)
        tree = git.changed_tree(previous, {"a.txt": b"alpha", "nested/b.txt": b"beta"})
        revision = files.snapshot(identifier, tree, head, previous)
        original = files.materialize

        def interrupt(*args: object) -> None:
            raise OSError("simulated process interruption")

        monkeypatch.setattr(files, "materialize", interrupt)
        with pytest.raises(OSError):
            files.apply(identifier, "main", revision)
        monkeypatch.setattr(files, "materialize", original)
    restarted = WorktreeStorage(GitRepository(tmp_path, UUID(git.path.stem)))
    with git.locked():
        restarted.recover()
        assert git.head("main") == head
        assert restarted.revision(identifier) == revision
        assert (restarted.path(identifier) / "nested/b.txt").read_text() == "beta"
        assert not restarted.journal.exists()


def test_main_protection_missing_checkout_and_conflicting_alias(
    native: tuple[TestClient, str, GitRepository],
) -> None:
    import shutil

    client, project, git = native
    root = f"/api/v1/projects/{project}/worktrees"
    auth = headers("owner")
    add_member(client, project, "reader", "READ_ONLY")
    main = client.get(root, headers=headers("reader")).json()[0]
    url = root + "/" + main["id"]
    save = client.post(
        url + "/save",
        headers={**auth, "Idempotency-Key": "main-save"},
        json={
            "expected_revision": main["revision"],
            "changes": [{"path": "a", "content_base64": "YQ=="}],
        },
    ).json()
    removal = client.post(
        url + "/remove",
        headers={**auth, "Idempotency-Key": "main-remove"},
        json={"expected_revision": save["revision"], "discard_changes": True},
    )
    assert removal.status_code == 409
    assert client.get(url, headers=auth).json()["revision"] == save["revision"]
    shutil.rmtree(WorktreeStorage(git).path(UUID(main["id"])))
    assert client.get(url, headers=auth).json()["lifecycle"] == "unavailable"
    restored = client.post(url + "/restore", headers=auth)
    assert restored.status_code == 200, restored.text
    assert restored.json()["revision"] == save["revision"]
    assert (WorktreeStorage(git).path(UUID(main["id"])) / "a").read_text() == "a"
    mismatch = client.post(
        "/api/v1/agent-sessions",
        headers=auth,
        json={
            "project_id": project,
            "worktree_id": main["id"],
            "task_id": str(uuid4()),
            "agent_kind": "RESEARCHER",
        },
    )
    assert mismatch.status_code == 422


def test_native_migration_retains_old_ids_and_is_resumable(
    native: tuple[TestClient, str, GitRepository],
) -> None:
    from polycolab.db.stores.repositories import SqlRepositoryStore
    from polycolab.db.transaction import SqlAlchemyTransaction
    from polycolab.projects.worktree_service import WorktreeService

    client, project, git = native
    auth = headers("owner")
    legacy = client.post(
        f"/api/v1/projects/{project}/tasks",
        headers=auth,
        json={"client_request_id": str(uuid4()), "title": "Existing branch"},
    ).json()
    root = f"/api/v1/projects/{project}/worktrees"
    assert client.get(root, headers=auth).status_code == 409
    user = client.get("/api/v1/users/me", headers=auth).json()
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as db:
        instance = WorktreeService(
            SqlAlchemyTransaction(db),
            SqlRepositoryStore(db),
            git,
            UUID(project),
            UUID(user["id"]),
        )
        with instance.open():
            instance.materialize()
            before = instance.files.revision(UUID(legacy["id"]))
            instance.materialize()
            assert instance.files.revision(UUID(legacy["id"])) == before
    migrated = client.get(root + "/" + legacy["id"], headers=auth).json()
    assert migrated["branch"] == legacy["branch"]
    assert migrated["created_by_user_id"] == legacy["created_by_user_id"]
    assert migrated["lifecycle"] == "active"


def test_merge_requires_clean_files_and_exact_saved_revisions(
    native: tuple[TestClient, str, GitRepository],
) -> None:
    client, project, _ = native
    auth = headers("owner")
    root = f"/api/v1/projects/{project}"
    main = client.get(root + "/worktrees", headers=auth).json()[0]
    branch = client.post(
        root + "/worktrees",
        headers=auth,
        json={"client_request_id": str(uuid4()), "title": "Proof", "branch": "proof"},
    ).json()
    url = root + "/worktrees/" + branch["id"]
    saved = client.post(
        url + "/save",
        headers={**auth, "Idempotency-Key": "save"},
        json={
            "expected_revision": branch["revision"],
            "changes": [{"path": "proof", "content_base64": "eA=="}],
        },
    ).json()
    merge_url = root + "/repository/merge"
    assert client.get(merge_url, headers=auth, params={"source": "proof"}).status_code == 409
    assert (
        client.post(
            url + "/commit",
            headers={**auth, "Idempotency-Key": "commit"},
            json={"expected_revision": saved["revision"], "message": "Proof"},
        ).status_code
        == 200
    )
    preview = client.get(merge_url, headers=auth, params={"source": "proof"}).json()
    body = {
        "source": "proof",
        "expected_target": preview["target_commit"],
        "expected_source": preview["source_commit"],
        "expected_target_revision": preview["target_revision"],
        "expected_source_revision": preview["source_revision"],
    }
    discard = client.post(
        root + "/worktrees/" + main["id"] + "/discard",
        headers={**auth, "Idempotency-Key": "discard"},
        json={"expected_revision": main["revision"]},
    ).json()
    assert (
        client.post(
            merge_url, headers={**auth, "Idempotency-Key": "stale-merge"}, json=body
        ).status_code
        == 409
    )
    body["expected_target_revision"] = discard["revision"]
    result = client.post(merge_url, headers={**auth, "Idempotency-Key": "merge"}, json=body)
    assert result.status_code == 200, result.text
    assert (
        client.post(merge_url, headers={**auth, "Idempotency-Key": "merge"}, json=body).json()
        == result.json()
    )
    main = client.get(root + "/worktrees/" + main["id"], headers=auth).json()
    assert not main["changed_files"]
    assert main["files"][0]["path"] == "proof"

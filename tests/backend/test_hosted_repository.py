from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_codex_runtime import spec
from test_hosted_artifacts import OWNER, WORKER
from test_runtime_api import _queue_run

from polycolab.db.models import SqlAgentRun, SqlAgentSession, SqlResearchScope, SqlUser
from polycolab.entities.enums import AgentRunStatus, ResearchScopeKind
from polycolab.entities.time import utc_now
from polycolab.execution import guest_repository


def repository_claim(
    client: TestClient,
    tmp_path: Path,
    *,
    disabled: bool = False,
    task_copy: bool = False,
    native_copy: bool = False,
) -> tuple[Any, str, dict[str, Any], str]:
    app, run_id = _queue_run(client)
    app.state.settings.workspace_repository_directory = tmp_path / "repositories"
    app.state.settings.runtime_codex_image = spec().image
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        db.get(SqlUser, run.requested_by_user_id).subject = "owner"
        db.add(SqlResearchScope(scope_kind=ResearchScopeKind.WORKSPACE, project_id=run.project_id))
        run.status = AgentRunStatus.FAILED
        url = f"/api/v1/workspaces/{run.project_id}/repository"
        session_id = run.session_id
        db.commit()
    if task_copy:
        task = client.post(
            url.removesuffix("/repository") + "/tasks",
            headers=OWNER,
            json={"client_request_id": str(uuid4()), "title": "Shared task copy"},
        )
        assert task.status_code == 201, task.text
        from uuid import UUID

        with app.state.session_factory() as db:
            db.get(SqlAgentSession, session_id).task_id = UUID(task.json()["id"])
            db.commit()
    enabled = client.put(f"{url}/sessions/{session_id}", headers=OWNER)
    assert enabled.status_code == 200, enabled.text
    if native_copy:
        from uuid import UUID

        from polycolab.db.stores.repositories import SqlRepositoryStore
        from polycolab.db.transaction import SqlAlchemyTransaction
        from polycolab.workspaces.git_storage import GitRepository
        from polycolab.workspaces.worktree_service import WorktreeService

        with app.state.session_factory() as db:
            previous = db.get(SqlAgentRun, run_id)
            instance = WorktreeService(
                SqlAlchemyTransaction(db),
                SqlRepositoryStore(db),
                GitRepository(tmp_path / "repositories", previous.project_id),
                previous.project_id,
                previous.requested_by_user_id,
            )
            with instance.open():
                instance.materialize()
                main = instance.task_for_branch("main")
                db.get(SqlAgentSession, session_id).task_id = main.id
                db.commit()
        trees_url = url.removesuffix("/repository") + "/worktrees"
        tree = client.get(f"{trees_url}/{main.id}", headers=OWNER).json()
        seeded = client.post(
            f"{trees_url}/{main.id}/save",
            headers={**OWNER, "Idempotency-Key": "seed"},
            json={
                "expected_revision": tree["revision"],
                "changes": [{"path": "human.txt", "content_base64": "aHVtYW4="}],
            },
        )
        assert seeded.status_code == 200, seeded.text
    with app.state.session_factory() as db:
        from polycolab.agents.sessions import append_user_message_and_queue_run

        previous = db.get(SqlAgentRun, run_id)
        _, run = append_user_message_and_queue_run(
            db,
            session_id=previous.session_id,
            requested_by_user_id=previous.requested_by_user_id,
            gateway_profile_id=previous.gateway_profile_id,
            content_md="Work on the saved repository.",
            runtime_spec=spec().model_dump(mode="json"),
            deadline_at=utc_now() + timedelta(minutes=5),
        )
        run_id = run.id
        db.commit()
    # API/transport test; native executor readiness is exercised separately.
    app.state.settings.runtime_codex_image = None
    if disabled:
        app.state.settings.workspace_repository_directory = None
    if native_copy:
        old_controller = client.post(
            "/internal/v1/runtime/claims",
            headers=WORKER,
            json={"worker_id": "hosted", "engine": "codex", "protocol_version": 3},
        )
        assert old_controller.status_code == 409, old_controller.text
        assert "executor_protocol_mismatch" in old_controller.text
    response = client.post(
        "/internal/v1/runtime/claims",
        headers=WORKER,
        json={"worker_id": "hosted", "engine": "codex"},
    )
    if disabled:
        assert response.status_code == 204, response.text
        return app, str(run_id), {}, url
    assert response.status_code == 200, response.text
    return app, str(run_id), response.json(), url


@pytest.mark.parametrize("task_copy", [False, True])
def test_hosted_checkout_save_completion_and_fencing(
    client: TestClient, tmp_path: Path, task_copy: bool
) -> None:
    _, run_id, claim, url = repository_claim(client, tmp_path, task_copy=task_copy)
    binding = claim["repository"]
    assert binding["branch"].startswith("tasks/" if task_copy else "sessions/")
    lease = {"worker_id": "hosted", "lease_generation": claim["lease_generation"]}
    internal = f"/internal/hosted/runs/{run_id}/repository"
    finish_url = f"/internal/v1/runtime/runs/{run_id}/finish"
    finish = {**lease, "status": "COMPLETED", "final_message_md": "Done"}
    assert client.post(finish_url, headers=WORKER, json=finish).status_code == 409
    assert (
        client.get(url, headers=OWNER, params={"branch": binding["branch"]}).json()["writable"]
        is False
    )
    checkout = client.get(internal, headers=WORKER, params=lease)
    assert checkout.status_code == 200, checkout.text
    inputs, outputs, workspace = tmp_path / "inputs", tmp_path / "outputs", tmp_path / "workspace"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "workspace.bundle").write_bytes(checkout.content)
    (inputs / "workspace.json").write_text(json.dumps(binding))
    metadata = guest_repository.checkout(inputs, workspace)
    assert metadata is not None
    (workspace / "proof.lean").write_text("-- saved research\n")
    commit = guest_repository.checkpoint(metadata, workspace, outputs)
    data = (outputs / "workspace.bundle").read_bytes()
    assert (
        client.post(
            internal,
            headers=WORKER,
            params={**lease, "lease_generation": lease["lease_generation"] + 1},
            content=data,
        ).status_code
        == 409
    )
    saved = client.post(internal, headers=WORKER, params=lease, content=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["commit"] == commit
    assert client.post(internal, headers=WORKER, params=lease, content=data).json() == saved.json()
    assert client.get(f"{url}/runs/{run_id}", headers=OWNER).json() == {
        "input_commit": binding["commit"],
        "output_commit": commit,
    }
    assert client.post(finish_url, headers=WORKER, json=finish).status_code == 204
    assert client.post(internal, headers=WORKER, params=lease, content=data).status_code == 409
    main = client.get(url, headers=OWNER).json()["commit"]
    preview = client.get(url + "/merge", headers=OWNER, params={"source": binding["branch"]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["conflicts"] == []
    merged = client.post(
        url + "/merge",
        headers={**OWNER, "Idempotency-Key": "merge"},
        json={"source": binding["branch"], "expected_target": main, "expected_source": commit},
    )
    assert merged.status_code == 200, merged.text
    assert client.get(url, headers=OWNER).json()["files"][0]["path"] == "proof.lean"


def test_cancelled_run_cannot_export(client: TestClient, tmp_path: Path) -> None:
    app, run_id, claim, _ = repository_claim(client, tmp_path)
    from uuid import UUID

    with app.state.session_factory() as db:
        db.get(SqlAgentRun, UUID(run_id)).cancel_requested_at = utc_now()
        db.commit()
    response = client.post(
        f"/internal/hosted/runs/{run_id}/repository",
        headers=WORKER,
        params={"worker_id": "hosted", "lease_generation": claim["lease_generation"]},
        content=b"not a bundle",
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "lease_lost"


def test_repository_session_fails_closed_when_storage_disabled(
    client: TestClient, tmp_path: Path
) -> None:
    from uuid import UUID

    app, run_id, _, _ = repository_claim(client, tmp_path, disabled=True)
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run.status == AgentRunStatus.FAILED
        assert run.failure_code == "context_unavailable"


def test_native_agent_sees_saved_overlay_and_leaves_human_review(
    client: TestClient, tmp_path: Path
) -> None:
    _, run_id, claim, url = repository_claim(client, tmp_path, native_copy=True)
    binding = claim["repository"]
    assert binding["branch"] == "main"
    lease = {"worker_id": "hosted", "lease_generation": claim["lease_generation"]}
    internal = f"/internal/hosted/runs/{run_id}/repository"
    tree_url = url.removesuffix("/repository") + "/worktrees/" + binding["worktree_id"]
    assert not client.get(tree_url, headers=OWNER).json()["writable"]
    blocked = client.post(
        tree_url + "/discard",
        headers={**OWNER, "Idempotency-Key": "blocked"},
        json={"expected_revision": binding["revision"]},
    )
    assert blocked.status_code == 409
    inputs, outputs, workspace = tmp_path / "inputs", tmp_path / "outputs", tmp_path / "workspace"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "workspace.bundle").write_bytes(
        client.get(internal, headers=WORKER, params=lease).content
    )
    (inputs / "workspace.json").write_text(json.dumps(binding))
    metadata = guest_repository.checkout(inputs, workspace)
    assert metadata is not None
    assert (workspace / "human.txt").read_text() == "human"
    assert guest_repository.git(workspace, "rev-parse", "HEAD") == binding["commit"]
    assert guest_repository.git(workspace, "status", "--porcelain")
    (workspace / "agent.txt").write_text("agent")
    guest_commit = guest_repository.checkpoint(metadata, workspace, outputs)
    saved = client.post(
        internal, headers=WORKER, params=lease, content=(outputs / "workspace.bundle").read_bytes()
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["commit"] != guest_commit
    state = client.get(tree_url, headers=OWNER).json()
    assert state["head_commit"] == binding["commit"]
    assert {file["path"] for file in state["changed_files"]} == {"human.txt", "agent.txt"}
    finish = client.post(
        f"/internal/v1/runtime/runs/{run_id}/finish",
        headers=WORKER,
        json={**lease, "status": "COMPLETED", "final_message_md": "Ready for review"},
    )
    assert finish.status_code == 204, finish.text
    assert client.get(tree_url, headers=OWNER).json()["writable"]

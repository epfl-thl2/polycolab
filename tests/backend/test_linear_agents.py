"""Real Git/Yjs hosted transport: snapshots, refresh, integration, and conflict privacy."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_hosted_artifacts import OWNER, WORKER
from test_hosted_scheduler import (
    hosted_client as hosted_client,
)
from test_hosted_scheduler import (
    new_hosted,
)
from test_hosted_scheduler import (
    scheduler_pg_schema as scheduler_pg_schema,
)
from test_linear_workspace import (
    collaboration_url as collaboration_url,
)
from test_linear_workspace import (
    create_file,
    write,
)
from test_sessions_api import add_member, headers

from polycolab.db.models import SqlAgentRun, SqlProject, SqlResearchScope, SqlUser
from polycolab.entities.enums import ResearchScopeKind
from polycolab.execution import guest_repository


@pytest.fixture
def agent(hosted_client: TestClient, tmp_path: Path, collaboration_url: str) -> tuple[Any, ...]:
    client = hosted_client
    run_id = new_hosted(client)
    app: Any = client.app
    app.state.settings.project_repository_directory = tmp_path / "repositories"
    app.state.settings.collaboration_url = collaboration_url
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        project_id = str(run.project_id)
        db.get(SqlUser, run.requested_by_user_id).subject = "owner"
        db.get(SqlProject, run.project_id).workspace_mode = "linear"
        db.add(SqlResearchScope(scope_kind=ResearchScopeKind.PROJECT, project_id=run.project_id))
        db.commit()
    root = f"/api/v1/projects/{project_id}/linear"
    command = create_file("notes.txt", "one\ntwo\nthree\nfour\nfive\n")
    assert write(client, root, [command]).status_code == 200
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers=WORKER,
        json={"worker_id": "hosted", "engine": "codex"},
    )
    assert claim.status_code == 200, claim.text
    binding = claim.json()["repository"]
    assert binding["mode"] == "linear"
    lease = {
        "worker_id": "hosted",
        "lease_generation": claim.json()["lease_generation"],
    }
    internal = f"/internal/hosted/runs/{run_id}"
    checkout = client.get(internal + "/repository", headers=WORKER, params=lease)
    assert checkout.status_code == 200, checkout.text
    inputs, outputs, project = (
        tmp_path / "inputs",
        tmp_path / "outputs",
        tmp_path / "project",
    )
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "workspace.bundle").write_bytes(checkout.content)
    (inputs / "workspace.json").write_text(json.dumps(binding))
    metadata = guest_repository.checkout(inputs, project)
    assert metadata is not None
    return client, root, internal, lease, metadata, project, outputs, command


def test_snapshot_merges_independent_edits_and_revert(agent: tuple[Any, ...]) -> None:
    client, root, internal, lease, metadata, project, outputs, command = agent
    (project / "notes.txt").write_text("AI\ntwo\nthree\nfour\nfive\n")
    human = {
        "kind": "replace",
        "file_id": command["file_id"],
        "content_base64": base64.b64encode(b"one\ntwo\nthree\nfour\nHuman\n").decode(),
    }
    assert write(client, root, [human], sequence=1).status_code == 200
    guest_repository.checkpoint(metadata, project, outputs)
    result = client.post(
        internal + "/repository",
        headers=WORKER,
        params=lease,
        content=(outputs / "workspace.bundle").read_bytes(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["application_status"] == "applied"
    saved = client.get(root + "/files/" + command["file_id"], headers=OWNER).json()
    assert base64.b64decode(saved["content_base64"]) == b"AI\ntwo\nthree\nfour\nHuman\n"
    reverted = client.post(root + f"/batches/{result.json()['batch_id']}/revert", headers=OWNER)
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "applied"
    saved = client.get(root + "/files/" + command["file_id"], headers=OWNER).json()
    assert base64.b64decode(saved["content_base64"]) == b"one\ntwo\nthree\nfour\nHuman\n"


def test_conflict_is_private_and_new_file_is_not_partially_applied(
    agent: tuple[Any, ...],
) -> None:
    client, root, internal, lease, metadata, project, outputs, command = agent
    (project / "notes.txt").write_text("AI changed this\n")
    (project / "new.txt").write_text("Must stay private until the whole result applies")
    assert (
        write(
            client,
            root,
            [
                {
                    "kind": "replace",
                    "file_id": command["file_id"],
                    "content_base64": base64.b64encode(b"Human changed this\n").decode(),
                }
            ],
            sequence=1,
        ).status_code
        == 200
    )
    guest_repository.checkpoint(metadata, project, outputs)
    result = client.post(
        internal + "/repository",
        headers=WORKER,
        params=lease,
        content=(outputs / "workspace.bundle").read_bytes(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["application_status"] == "pending"
    assert len(client.get(root, headers=OWNER).json()["files"]) == 1
    project_id = root.split("/")[4]
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    assert client.get(root + "/batches", headers=headers("contributor")).json() == []
    assert (
        client.post(
            root + f"/batches/{result.json()['batch_id']}/retry",
            headers=headers("contributor"),
        ).status_code
        == 404
    )
    assert client.get(root, headers=OWNER).json()["sequence"] == 2


def test_refresh_requires_ack_and_preserves_local_changes(
    agent: tuple[Any, ...],
) -> None:
    client, root, internal, lease, metadata, project, outputs, command = agent
    (project / "notes.txt").write_text("AI\ntwo\nthree\nfour\nfive\n")
    assert (
        write(client, root, [create_file("human.txt", "new shared file")], sequence=1).status_code
        == 200
    )
    status = client.get(internal + "/workspace-status", headers=WORKER, params=lease)
    assert status.status_code == 200, status.text
    assert status.json()["sequence"] == 2
    guest_repository.checkpoint(metadata, project, outputs)
    data = (outputs / "workspace.bundle").read_bytes()
    prepared = client.post(
        internal + "/workspace-refresh",
        headers=WORKER,
        params={**lease, "key": "refresh-1"},
        content=data,
    )
    assert prepared.status_code == 200, prepared.text
    value = prepared.json()
    assert "error" not in value, value
    assert (
        client.post(
            internal + "/repository", headers=WORKER, params=lease, content=data
        ).status_code
        == 409
    )
    guest_repository.refresh(
        metadata,
        base64.b64decode(value["bundle"]),
        value["base"],
        value["commit"],
        project,
    )
    assert (project / "human.txt").read_text() == "new shared file"
    assert (project / "notes.txt").read_text().startswith("AI\n")
    ack = client.post(
        internal + "/workspace-refresh-ack",
        headers=WORKER,
        params={**lease, "generation": value["generation"]},
    )
    assert ack.status_code == 200, ack.text
    guest_repository.checkpoint(metadata, project, outputs)
    result = client.post(
        internal + "/repository",
        headers=WORKER,
        params=lease,
        content=(outputs / "workspace.bundle").read_bytes(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["application_status"] == "applied"


def test_restored_project_keeps_old_agent_result_pending(agent: tuple[Any, ...]) -> None:
    client, root, internal, lease, metadata, project, outputs, command = agent
    checkpoint = client.get(root + "/checkpoints", headers=OWNER).json()[0]
    restored = client.post(
        root + "/restore",
        headers={**OWNER, "Idempotency-Key": "restore-during-agent"},
        json={"epoch": 1, "sequence": 1, "checkpoint_id": checkpoint["id"]},
    )
    assert restored.status_code == 200, restored.text
    (project / "notes.txt").write_text("Old agent result\n")
    guest_repository.checkpoint(metadata, project, outputs)
    result = client.post(
        internal + "/repository",
        headers=WORKER,
        params=lease,
        content=(outputs / "workspace.bundle").read_bytes(),
    )
    assert result.status_code == 200, result.text
    assert result.json()["application_status"] == "pending"
    current = client.get(root, headers=OWNER).json()
    assert current["epoch"] == 2
    assert current["sequence"] == restored.json()["sequence"]
    saved = client.get(root + "/files/" + current["files"][0]["id"], headers=OWNER).json()
    assert base64.b64decode(saved["content_base64"]) == b"one\ntwo\nthree\nfour\nfive\n"


def test_cancelled_agent_cannot_apply_files(agent: tuple[Any, ...]) -> None:
    client, root, internal, lease, metadata, project, outputs, command = agent
    (project / "notes.txt").write_text("Cancelled result\n")
    guest_repository.checkpoint(metadata, project, outputs)
    with client.app.state.session_factory() as db:
        run = db.get(SqlAgentRun, UUID(internal.rsplit("/", 1)[1]))
        run.cancel_requested_at = datetime.now(UTC)
        db.commit()
    result = client.post(
        internal + "/repository",
        headers=WORKER,
        params=lease,
        content=(outputs / "workspace.bundle").read_bytes(),
    )
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "lease_lost"
    assert client.get(root, headers=OWNER).json()["sequence"] == 1
    assert client.get(root + "/batches", headers=OWNER).json() == []

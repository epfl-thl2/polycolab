from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from test_artifacts import MemoryS3
from test_codex_runtime import spec
from test_runtime_api import _queue_run

from polycolab.artifacts.storage import GarageStorage
from polycolab.db.models import ResearchScopeKind, SqlAgentRun, SqlResearchScope, SqlUser
from polycolab.entities.time import utc_now
from polycolab.execution.allocator import admit


def hosted_claim(client: TestClient) -> tuple[Any, UUID, dict[str, Any]]:
    app, run_id = _queue_run(client)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "hosted-test")
    with app.state.session_factory() as session:
        run = session.get(SqlAgentRun, run_id)
        session.get(SqlUser, run.requested_by_user_id).subject = "owner"
        session.add(
            SqlResearchScope(scope_kind=ResearchScopeKind.PROJECT, project_id=run.project_id)
        )
        run.runtime_spec = spec().model_dump(mode="json")
        run.deadline_at = utc_now() + timedelta(minutes=5)
        admit(session, run)
        session.commit()
    response = client.post(
        "/internal/v1/runtime/claims",
        headers=WORKER,
        json={"worker_id": "hosted", "engine": "codex"},
    )
    assert response.status_code == 200, response.text
    return app, run_id, response.json()


WORKER = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
OWNER = {"Authorization": "Bearer owner"}


def test_export_is_private_until_success_and_fenced(client: TestClient) -> None:
    app, run_id, claim = hosted_claim(client)
    data = b"private result"
    params = {
        "worker_id": "hosted",
        "lease_generation": claim["lease_generation"],
        "path": "result.txt",
        "display_name": "Result.txt",
        "media_type": "text/plain",
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
    }
    url = f"/internal/hosted/runs/{run_id}/artifacts"
    response = client.post(url, headers=WORKER, params=params, content=data)
    assert response.status_code == 200, response.text
    artifact = response.json()["artifact_id"]
    assert client.post(url, headers=WORKER, params=params, content=data).json() == response.json()
    assert client.get(f"/api/v1/artifacts/{artifact}/content", headers=OWNER).status_code == 404
    finish = client.post(
        f"/internal/v1/runtime/runs/{run_id}/finish",
        headers=WORKER,
        json={
            "worker_id": "hosted",
            "lease_generation": claim["lease_generation"],
            "status": "COMPLETED",
            "final_message_md": "Done.",
        },
    )
    assert finish.status_code == 204, finish.text
    listing = client.get(f"/api/v1/agent-runs/{run_id}/artifacts", headers=OWNER)
    assert listing.status_code == 200, listing.text
    assert listing.json()[0]["artifact_id"] == artifact
    assert (
        client.get(
            f"/api/v1/agent-runs/{run_id}/artifacts/{artifact}/content", headers=OWNER
        ).content
        == data
    )
    assert client.get(f"/api/v1/agent-runs/{run_id}/artifacts/{artifact}/content").status_code in {
        401,
        404,
    }
    assert client.post(url, headers=WORKER, params=params, content=data).status_code == 409


def test_readiness_expires_without_hiding_history(client: TestClient) -> None:
    from polycolab.db.models import SqlHostedExecutor

    app, run_id, claim = hosted_claim(client)
    app.state.settings.runtime_codex_image = spec().image
    app.state.settings.feature_agent_execution_enabled = True
    before = client.get("/api/v1/agent-capabilities", headers=OWNER).json()
    assert before == {
        "sessions": True,
        "execution_available": False,
        "hosted_agents": False,
        "verification": False,
    }
    ready = client.post(
        "/internal/v1/runtime/executors/readiness",
        headers=WORKER,
        json={
            "worker_id": "hosted",
            "engine": "codex",
            "image_digest": spec().image.rsplit(":", 1)[-1],
            "incarnation": "test-incarnation",
            "slot_states": {str(i): "AVAILABLE" for i in range(4)},
            "capacity": 4,
        },
    )
    assert ready.status_code == 204
    assert client.get("/api/v1/agent-capabilities", headers=OWNER).json()["hosted_agents"]
    with app.state.session_factory() as session:
        session.get(SqlHostedExecutor, "hosted").expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    assert not client.get("/api/v1/agent-capabilities", headers=OWNER).json()["hosted_agents"]
    assert client.get(f"/api/v1/agent-runs/{run_id}", headers=OWNER).status_code == 200

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpcore
import httpx
import pytest
from fastapi.testclient import TestClient
from httpcore._backends.mock import AsyncMockBackend
from test_hosted_artifacts import WORKER, hosted_claim

from polycolab.agents.recovery import reconcile
from polycolab.agents.runtime.client import RuntimeClient
from polycolab.db.models import SqlAgentRun, SqlHostedModelRequest
from polycolab.entities.enums import AgentRunStatus
from polycolab.entities.time import utc_now
from polycolab.model_gateway import async_transport


def test_actual_httpcore_transport_frames_json(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        pool = httpcore.AsyncConnectionPool(
            network_backend=AsyncMockBackend([b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"])
        )
        monkeypatch.setattr(async_transport, "resolve_addresses", lambda *_: ["93.184.216.34"])
        monkeypatch.setattr(httpcore, "AsyncConnectionPool", lambda **_: pool)
        assert (
            await async_transport.responses(
                base_url="https://models.example/v1",
                api_key="dummy",
                payload={"model": "test"},
                max_bytes=100,
            )
            == b"{}"
        )

    asyncio.run(scenario())


def test_response_timeout_and_safe_control_retry() -> None:
    async def scenario() -> None:
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if request.url.path.endswith("responses"):
                assert request.extensions["timeout"]["read"] > 59
            elif calls == 1:
                return httpx.Response(503)
            return httpx.Response(204)

        client = RuntimeClient("http://localhost", "dummy", transport=httpx.MockTransport(handler))
        await client.post("/finish", {}, timeout=1)
        assert calls == 2
        await client.post("/responses", {}, timeout=60)
        await client.close()

    asyncio.run(scenario())


def test_expired_deadline_is_finalized_without_live_lease(client: TestClient) -> None:
    app, run_id, claim = hosted_claim(client)
    with app.state.session_factory() as session:
        run = session.get(SqlAgentRun, run_id)
        run.deadline_at = run.lease_expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
    response = client.post(
        f"/internal/v1/runtime/runs/{run_id}/finish",
        headers=WORKER,
        json={
            "worker_id": "hosted",
            "lease_generation": claim["lease_generation"],
            "status": "TIMED_OUT",
            "failure_code": "deadline_exceeded",
        },
    )
    assert response.status_code == 204, response.text
    assert client.send(response.request).status_code == 204
    with app.state.session_factory() as session:
        assert session.get(SqlAgentRun, run_id).status == AgentRunStatus.TIMED_OUT


@pytest.mark.parametrize("dispatched", [False, True])
def test_recovery_requires_resume_after_possible_effects(
    client: TestClient, dispatched: bool
) -> None:
    app, run_id, claim = hosted_claim(client)
    with app.state.session_factory() as session:
        run = session.get(SqlAgentRun, run_id)
        run.lease_expires_at = utc_now() - timedelta(seconds=1)
        if dispatched:
            session.add(
                SqlHostedModelRequest(
                    run_id=run_id,
                    generation=claim["lease_generation"],
                    request_key="uncertain",
                    request_digest="0" * 64,
                    input_tokens=10,
                    output_tokens=10,
                    cost_microusd=1,
                    settle_by=utc_now() + timedelta(seconds=60),
                )
            )
        session.commit()
        assert reconcile(session) == 1
        run = session.get(SqlAgentRun, run_id)
        assert run.status == (AgentRunStatus.FAILED if dispatched else AgentRunStatus.QUEUED)
        if dispatched:
            assert run.failure_code == "runner_lost_resume_required"
        assert reconcile(session) == 0


def test_completion_retry_must_match_exact_text(client: TestClient) -> None:
    _, run_id, claim = hosted_claim(client)
    body: dict[str, Any] = {
        "worker_id": "hosted",
        "lease_generation": claim["lease_generation"],
        "status": "COMPLETED",
        "final_message_md": "First answer",
    }
    url = f"/internal/v1/runtime/runs/{run_id}/finish"
    assert client.post(url, headers=WORKER, json=body).status_code == 204
    assert client.post(url, headers=WORKER, json=body).status_code == 204
    body["final_message_md"] = "Different answer"
    assert client.post(url, headers=WORKER, json=body).status_code == 409


def test_history_remains_available_after_readiness_loss(client: TestClient) -> None:
    from test_hosted_artifacts import OWNER

    app, run_id, _ = hosted_claim(client)
    with app.state.session_factory() as db:
        session_id = db.get(SqlAgentRun, run_id).session_id
    response = client.get(f"/api/v1/agent-sessions/{session_id}/runs?limit=1", headers=OWNER)
    assert response.status_code == 200
    assert response.json()[0]["id"] == str(run_id)
    assert "X-Next-Cursor" not in response.headers


def test_restart_quarantines_only_uncertain_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from polycolab.execution.linux import LinuxRuntime, atomic_record
    from polycolab.execution.sandbox import SandboxUnavailable

    async def scenario() -> None:
        runtime = LinuxRuntime(tmp_path, (), 2)
        monkeypatch.setattr(runtime, "check_ready", AsyncMock())
        stop = AsyncMock(side_effect=[SandboxUnavailable("sandbox_cleanup_unconfirmed"), None])
        monkeypatch.setattr(runtime, "_stop", stop)
        (tmp_path / "attempts").mkdir()
        for index in range(2):
            slot = tmp_path / "slots" / str(index)
            (slot / "work").mkdir(parents=True)
            (slot / "work" / "private.txt").write_text("discard")
            atomic_record(
                tmp_path / "attempts" / f"{index}.json",
                {
                    "version": 1,
                    "unit": f"polycolab-attempt-{index}.service",
                    "slot": str(slot),
                    "run_id": str(index),
                    "generation": 1,
                    "worker_id": "host",
                },
            )
        await runtime.reconcile()
        assert runtime.states == {0: "QUARANTINED", 1: "AVAILABLE"}
        assert not (tmp_path / "slots" / "1" / "work").exists()
        async with runtime.reserve() as ordinal:
            assert ordinal == 1
        assert len(runtime.terminated) == 1

    asyncio.run(scenario())


def test_incomplete_response_keeps_validated_billable_usage() -> None:
    from test_codex_runtime import response_bytes

    from polycolab.model_gateway.responses import IncompleteResponse, completed_response

    data = (
        response_bytes()
        .replace(b"response.completed", b"response.incomplete")
        .replace(b'"completed"', b'"incomplete"')
    )
    with pytest.raises(IncompleteResponse) as caught:
        completed_response([data], max_bytes=1000, max_output_tokens=10)
    assert caught.value.usage["total_tokens"] > 0

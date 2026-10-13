from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
import structlog
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from polycolab.agents.runtime.contracts import ModelStreamFrame, ModelTurn, ToolCallDelta, Usage
from polycolab.agents.runtime.remote import (
    ApiBackedWorker,
    RuntimeClaim,
    RuntimeGateway,
    RuntimeGatewayError,
    RuntimeLeaseState,
    WorkerEventKind,
    WorkerTerminalStatus,
)
from polycolab.agents.sessions import (
    append_user_message_and_queue_run,
    create_agent_session,
    request_cancel,
)
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlGatewayProfile,
    SqlMembership,
    SqlProject,
    SqlUser,
)
from polycolab.entities.enums import (
    AgentRunStatus,
    PlatformAgentKind,
    ProjectRole,
    ProjectVisibility,
)
from polycolab.platform.observability import metrics


def _queue_run(client: TestClient) -> tuple[Any, UUID]:
    app = cast(Any, client.app)
    session = app.state.session_factory()
    user = SqlUser(issuer="https://issuer.example", subject="runtime-api-owner")
    session.add(user)
    session.commit()
    project = SqlProject(
        name="Runtime API project",
        visibility=ProjectVisibility.PRIVATE,
        created_by_user_id=user.id,
    )
    profile = SqlGatewayProfile(
        user_id=user.id,
        display_name="runtime profile",
        base_url="https://models.example/v1",
        model_id="runtime-model",
        credential_version=1,
        encrypted_credential=b"test",
        wrapped_data_key=b"test",
        encryption_key_version="test",
    )
    session.add_all((project, profile))
    session.commit()
    session.add(SqlMembership(project_id=project.id, user_id=user.id, role=ProjectRole.OWNER))
    session.commit()
    agent_session = create_agent_session(
        session,
        project_id=project.id,
        created_by_user_id=user.id,
        agent_kind=PlatformAgentKind.RESEARCHER,
    )
    _, run = append_user_message_and_queue_run(
        session,
        session_id=agent_session.id,
        requested_by_user_id=user.id,
        gateway_profile_id=profile.id,
        content_md="Check the private runtime boundary.",
    )
    run_id = run.id
    session.close()
    return app, run_id


def test_runtime_api_requires_worker_credential_and_owns_state_mutations(
    client: TestClient,
) -> None:
    app, run_id = _queue_run(client)
    assert (
        client.post("/internal/v1/runtime/claims", json={"worker_id": "worker-a"}).status_code
        == 401
    )
    headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    claim_response = client.post(
        "/internal/v1/runtime/claims", headers=headers, json={"worker_id": "worker-a"}
    )
    assert claim_response.status_code == 200
    claim = claim_response.json()
    assert claim["run_id"] == str(run_id)
    assert claim["model_id"] == "runtime-model"
    assert claim["messages"][-1]["content"] == "Check the private runtime boundary."
    lease = {"worker_id": "worker-a", "lease_generation": claim["lease_generation"]}

    heartbeat = client.post(
        f"/internal/v1/runtime/runs/{run_id}/lease", headers=headers, json=lease
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json() == {
        "active": True,
        "cancel_requested": False,
        "timed_out": False,
    }
    stale = client.post(
        f"/internal/v1/runtime/runs/{run_id}/lease",
        headers=headers,
        json={**lease, "lease_generation": claim["lease_generation"] + 1},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "lease_lost"
    grant = client.post(
        f"/internal/v1/runtime/runs/{run_id}/model-grants", headers=headers, json=lease
    )
    assert grant.status_code == 200
    assert isinstance(grant.json()["grant"], str)
    event = client.post(
        f"/internal/v1/runtime/runs/{run_id}/events",
        headers=headers,
        json={
            **lease,
            "idempotency_key": "test-delta",
            "kind": "ASSISTANT_DELTA",
            "payload": {"text": "Result"},
        },
    )
    assert event.status_code == 200
    usage = client.post(
        f"/internal/v1/runtime/runs/{run_id}/usage",
        headers=headers,
        json={
            **lease,
            "idempotency_key": "test-usage",
            "input_tokens": 2,
            "output_tokens": 1,
            "total_tokens": 3,
        },
    )
    assert usage.status_code == 200
    finish_payload = {
        **lease,
        "status": "COMPLETED",
        "failure_code": None,
        "final_message_md": "Result",
    }
    finished = client.post(
        f"/internal/v1/runtime/runs/{run_id}/finish",
        headers=headers,
        json=finish_payload,
    )
    assert finished.status_code == 204
    duplicate_finish = client.post(
        f"/internal/v1/runtime/runs/{run_id}/finish",
        headers=headers,
        json=finish_payload,
    )
    assert duplicate_finish.status_code == 204
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None and run.status is AgentRunStatus.COMPLETED
    finally:
        session.close()


def test_runtime_worker_credential_rotation_audit_and_expiry(client: TestClient) -> None:
    app = cast(Any, client.app)
    settings = app.state.settings
    settings.runtime_worker_token = SecretStr("current-runtime-token")
    settings.runtime_worker_previous_token = SecretStr("previous-runtime-token")
    settings.runtime_worker_previous_token_expires_at = datetime.now(UTC) + timedelta(minutes=5)

    with structlog.testing.capture_logs() as logs:
        overlap = client.post(
            "/internal/v1/runtime/claims",
            headers={"Authorization": "Bearer previous-runtime-token"},
            json={"worker_id": "worker-a"},
        )
    assert overlap.status_code == 204
    assert any(
        entry.get("event") == "runtime_worker_authentication"
        and entry.get("outcome") == "accepted_previous"
        and entry.get("credential_slot") == "previous"
        for entry in logs
    )

    settings.runtime_worker_previous_token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = client.post(
        "/internal/v1/runtime/claims",
        headers={"Authorization": "Bearer previous-runtime-token"},
        json={"worker_id": "worker-a"},
    )
    assert expired.status_code == 401
    current = client.post(
        "/internal/v1/runtime/claims",
        headers={"Authorization": "Bearer current-runtime-token"},
        json={"worker_id": "worker-a"},
    )
    assert current.status_code == 204
    rendered = metrics.render_prometheus()
    assert 'polycolab_runtime_worker_auth_total{outcome="accepted_previous"}' in rendered
    assert 'polycolab_runtime_worker_auth_total{outcome="expired_previous"}' in rendered


def test_runtime_api_bounds_requests_and_claim_envelopes(client: TestClient) -> None:
    app, run_id = _queue_run(client)
    headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    app.state.settings.runtime_api_max_request_bytes = 64
    oversized = client.post(
        "/internal/v1/runtime/claims",
        headers=headers,
        json={"worker_id": "x" * 200},
    )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "runtime_request_too_large"

    app.state.settings.runtime_api_max_request_bytes = 262_144
    app.state.settings.runtime_api_max_response_bytes = 128
    claim = client.post(
        "/internal/v1/runtime/claims", headers=headers, json={"worker_id": "worker-a"}
    )
    assert claim.status_code == 204
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        assert run.status is AgentRunStatus.FAILED
        assert run.failure_code == "execution_envelope_too_large"
    finally:
        session.close()


def test_runtime_api_recovers_crashed_worker_and_rejects_stale_duplicate_writes(
    client: TestClient,
) -> None:
    app, run_id = _queue_run(client)
    headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    first = client.post(
        "/internal/v1/runtime/claims", headers=headers, json={"worker_id": "worker-a"}
    ).json()
    first_lease = {
        "worker_id": "worker-a",
        "lease_generation": first["lease_generation"],
    }
    event_payload = {
        **first_lease,
        "idempotency_key": "duplicate-delta",
        "kind": "ASSISTANT_DELTA",
        "payload": {"text": "once"},
    }
    original = client.post(
        f"/internal/v1/runtime/runs/{run_id}/events",
        headers=headers,
        json=event_payload,
    )
    duplicate = client.post(
        f"/internal/v1/runtime/runs/{run_id}/events",
        headers=headers,
        json=event_payload,
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == original.json()
    conflict = client.post(
        f"/internal/v1/runtime/runs/{run_id}/events",
        headers=headers,
        json={**event_payload, "payload": {"text": "different"}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"

    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    finally:
        session.close()
    recovered = client.post(
        "/internal/v1/runtime/claims", headers=headers, json={"worker_id": "worker-b"}
    )
    assert recovered.status_code == 200
    assert recovered.json()["lease_generation"] > first["lease_generation"]
    stale = client.post(
        f"/internal/v1/runtime/runs/{run_id}/events",
        headers=headers,
        json={**event_payload, "idempotency_key": "stale-after-recovery"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "lease_lost"
    session = app.state.session_factory()
    try:
        assert (
            session.scalar(
                select(func.count(SqlAgentRunEvent.id)).where(
                    SqlAgentRunEvent.run_id == run_id,
                    SqlAgentRunEvent.idempotency_key == "duplicate-delta",
                )
            )
            == 1
        )
    finally:
        session.close()


def test_runtime_api_reports_cancellation_to_lease_owner(client: TestClient) -> None:
    app, run_id = _queue_run(client)
    headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    claim = client.post(
        "/internal/v1/runtime/claims", headers=headers, json={"worker_id": "worker-a"}
    ).json()
    session = app.state.session_factory()
    try:
        request_cancel(session, run_id=run_id)
    finally:
        session.close()
    heartbeat = client.post(
        f"/internal/v1/runtime/runs/{run_id}/lease",
        headers=headers,
        json={"worker_id": "worker-a", "lease_generation": claim["lease_generation"]},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["cancel_requested"] is True


@dataclass
class FakeRuntimeGateway(RuntimeGateway):
    claim_value: RuntimeClaim | None
    events: list[WorkerEventKind] = field(default_factory=list)
    finishes: list[tuple[WorkerTerminalStatus, str | None, str | None]] = field(
        default_factory=list
    )

    def claim(self, *, worker_id: str) -> RuntimeClaim | None:
        assert worker_id == "remote-worker"
        value, self.claim_value = self.claim_value, None
        return value

    def heartbeat(
        self, *, run_id: UUID, worker_id: str, lease_generation: int
    ) -> RuntimeLeaseState:
        return RuntimeLeaseState(cancel_requested=False, timed_out=False)

    def issue_model_grant(self, *, run_id: UUID, worker_id: str, lease_generation: int) -> str:
        return "one-use-grant"

    def append_event(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        kind: WorkerEventKind,
        payload: dict[str, object],
    ) -> int:
        self.events.append(kind)
        return len(self.events) + 1

    def record_usage(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        idempotency_key: str,
        frame: ModelStreamFrame,
    ) -> None:
        assert frame.usage is not None

    def finish(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_generation: int,
        status: WorkerTerminalStatus,
        failure_code: str | None,
        final_message_md: str | None = None,
    ) -> None:
        self.finishes.append((status, failure_code, final_message_md))


@dataclass
class FakeModelGateway:
    def stream(self, turn: ModelTurn, *, grant: str) -> Iterator[ModelStreamFrame]:
        assert grant == "one-use-grant"
        yield ModelStreamFrame(content="Remote result")
        yield ModelStreamFrame(finish_reason="stop")
        yield ModelStreamFrame(usage=Usage(completion_tokens=2, prompt_tokens=3, total_tokens=5))


@dataclass
class NoopToolGateway:
    def call(
        self,
        *,
        capability: str,
        name: str,
        arguments: dict[str, object],
        invocation: str,
        source_event_cursor: int | None,
    ) -> dict[str, object]:
        raise AssertionError("no tool call expected")


def test_remote_worker_completes_without_database_dependency() -> None:
    claim = RuntimeClaim(
        run_id=UUID("00000000-0000-0000-0000-000000000123"),
        lease_generation=1,
        model_id="test-model",
        messages=[{"role": "user", "content": "Run"}],
        tool_capability="tool-capability",
        max_output_tokens=100,
        max_model_rounds=2,
        max_tool_calls=4,
        max_tool_argument_bytes=1024,
        max_tool_result_bytes=1024,
        lease_for=timedelta(seconds=30),
    )
    runtime = FakeRuntimeGateway(claim)
    worker = ApiBackedWorker(
        worker_id="remote-worker",
        runtime_gateway=runtime,
        model_gateway=FakeModelGateway(),
        tool_gateway=NoopToolGateway(),
    )

    assert worker.run_once()
    assert runtime.events == ["ASSISTANT_DELTA"]
    assert runtime.finishes == [("COMPLETED", None, "Remote result")]


@pytest.mark.parametrize(
    "tool_name",
    ["write_object_version", "comment_on_object_version", "create_relation", "submit_proposal"],
)
def test_remote_worker_sends_trusted_mutation_event_cursor(tool_name: str) -> None:
    class MutationModel:
        def stream(self, turn: ModelTurn, *, grant: str) -> Iterator[ModelStreamFrame]:
            if not any(message.get("role") == "tool" for message in turn.messages):
                yield ModelStreamFrame(
                    tool_call_deltas=(ToolCallDelta(index=0, name=tool_name, arguments="{}"),)
                )
                yield ModelStreamFrame(finish_reason="tool_calls")
            else:
                yield ModelStreamFrame(content="Saved", finish_reason="stop")
            yield ModelStreamFrame(
                usage=Usage(completion_tokens=1, prompt_tokens=1, total_tokens=2)
            )

    calls: list[tuple[str, str, int | None]] = []

    class MutationTools:
        def call(
            self,
            *,
            capability: str,
            name: str,
            arguments: dict[str, object],
            invocation: str,
            source_event_cursor: int | None,
        ) -> dict[str, object]:
            calls.append((name, invocation, source_event_cursor))
            return {"id": "saved"}

    claim = RuntimeClaim(
        run_id=UUID("00000000-0000-0000-0000-000000000123"),
        lease_generation=1,
        model_id="test-model",
        messages=[{"role": "user", "content": "Run"}],
        tool_capability="capability",
        max_output_tokens=100,
        max_model_rounds=2,
        max_tool_calls=4,
        max_tool_argument_bytes=1024,
        max_tool_result_bytes=1024,
        lease_for=timedelta(seconds=30),
    )
    runtime = FakeRuntimeGateway(claim)
    worker = ApiBackedWorker(
        worker_id="remote-worker",
        runtime_gateway=runtime,
        model_gateway=MutationModel(),
        tool_gateway=MutationTools(),
    )
    assert worker.run_once()
    assert calls == [(tool_name, f"tool-{claim.run_id}-1-0", 2)]
    assert runtime.finishes == [("COMPLETED", None, "Saved")]


def test_api_backed_worker_leaves_claim_recoverable_when_runtime_api_fails() -> None:
    class UnavailableRuntime(FakeRuntimeGateway):
        def heartbeat(
            self, *, run_id: UUID, worker_id: str, lease_generation: int
        ) -> RuntimeLeaseState:
            raise RuntimeGatewayError("runtime_api_unavailable")

    claim = RuntimeClaim(
        run_id=UUID("00000000-0000-0000-0000-000000000124"),
        lease_generation=1,
        model_id="test-model",
        messages=[{"role": "user", "content": "Run"}],
        tool_capability="tool-capability",
        max_output_tokens=100,
        max_model_rounds=2,
        max_tool_calls=4,
        max_tool_argument_bytes=1024,
        max_tool_result_bytes=1024,
        lease_for=timedelta(seconds=30),
    )
    runtime = UnavailableRuntime(claim)
    worker = ApiBackedWorker(
        worker_id="remote-worker",
        runtime_gateway=runtime,
        model_gateway=FakeModelGateway(),
        tool_gateway=NoopToolGateway(),
    )

    assert worker.run_once()
    assert runtime.finishes == []

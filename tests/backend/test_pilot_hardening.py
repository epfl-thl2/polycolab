from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

import polycolab.execution.limits as execution_limits
from polycolab.agents.routes.sessions import (
    _last_run_cursor,
    _last_session_cursor,
    _run_event_stream,
)
from polycolab.agents.sessions import (
    append_worker_event,
    claim_next_run,
    finish_run,
    record_usage,
    start_claimed_run,
)
from polycolab.db.models import (
    SqlAgentRun,
    SqlExecutionRateWindow,
    SqlOperationalMetricAggregate,
    SqlOperatorDiagnosticAccess,
)
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus, UsageSource
from polycolab.execution.limits import (
    ExecutionLimitExceeded,
    ExecutionLimits,
    enforce_execution_limits,
    enforce_next_round_budget,
    purge_expired_rate_windows,
)
from polycolab.platform.observability import metrics


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _app(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def _limits(
    *,
    requests_per_minute: int = 0,
    input_rate: int = 1,
    output_rate: int = 1,
    daily_tokens: int = 0,
    daily_cost: int = 0,
) -> ExecutionLimits:
    return ExecutionLimits(
        user_requests_per_minute=requests_per_minute,
        project_requests_per_minute=requests_per_minute,
        user_concurrent_runs=0,
        project_concurrent_runs=0,
        user_daily_tokens=daily_tokens,
        project_daily_tokens=daily_tokens,
        user_daily_cost_microusd=daily_cost,
        project_daily_cost_microusd=daily_cost,
        input_microusd_per_million_tokens=input_rate,
        output_microusd_per_million_tokens=output_rate,
        max_run_output_tokens=1,
        max_input_tokens_per_round=1,
        max_model_rounds=1,
        max_attempts=1,
    )


def _project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/projects",
        headers=_headers("owner"),
        json={"name": "Pilot project", "visibility": "PRIVATE"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def _profile(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=_headers("owner"),
        json={
            "display_name": "Pilot model",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "pilot-model",
            "api_key": "sk-pilot-secret",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def _session(client: TestClient, project_id: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/agent-sessions",
        headers=_headers("owner"),
        json={"project_id": project_id, "agent_kind": "RESEARCHER"},
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_public_projects_are_available_while_hosted_execution_is_disabled(
    client: TestClient,
) -> None:
    project = _project(client)
    public = client.post(
        "/api/v1/projects",
        headers=_headers("owner"),
        json={"name": "Public", "visibility": "PUBLIC"},
    )
    assert public.status_code == 201
    assert client.get(f"/api/v1/projects/{project['id']}").status_code == 404

    _app(client).state.settings.feature_agent_execution_enabled = False
    response = client.post(
        "/api/v1/agent-sessions",
        headers=_headers("owner"),
        json={"project_id": project["id"], "agent_kind": "RESEARCHER"},
    )
    assert response.status_code == 404


def test_public_reads_store_keyed_identifiers_without_client_addresses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _app(client).state.settings
    settings.public_read_requests_per_minute = 10
    settings.admission_scope_hmac_key = SecretStr("public-read-test-key")
    now = datetime(2026, 9, 5, tzinfo=UTC)
    monkeypatch.setattr("polycolab.app.application.utc_now", lambda: now)
    address = "192.0.2.10"
    with TestClient(_app(client), client=(address, 50000)) as anonymous:
        for _ in range(2):
            assert anonymous.get("/api/v1/catalogue").status_code == 200
    expected_id = UUID(
        bytes=hmac.new(
            settings.admission_hmac_key.encode(), address.encode(), hashlib.sha256
        ).digest()[:16]
    )
    with _app(client).state.session_factory() as db:
        row = db.scalars(
            select(SqlExecutionRateWindow).where(SqlExecutionRateWindow.scope == "public_ip")
        ).one()
        assert row.scope_id == expected_id
        assert row.count == 2
        persisted = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        assert address not in repr(persisted)


def test_sse_cursor_reconnects_are_rate_limited_after_authorization(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(client)
    profile = _profile(client)
    agent_session = _session(client, str(project["id"]))
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={
            "gateway_profile_id": profile["id"],
            "content_md": "Rate limit reconnects.",
            "client_request_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    run_id = queued.json()["run"]["id"]
    cancelled = client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=_headers("owner"))
    assert cancelled.status_code == 202
    _app(client).state.settings.sse_reconnects_per_minute = 1
    # Keep both requests in one rate bucket even when the wall clock crosses a minute.
    now = datetime(2026, 9, 9, 12, 0, 59, tzinfo=UTC)
    monkeypatch.setattr("polycolab.agents.routes.sessions.utc_now", lambda: now)

    first = client.get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={**_headers("owner"), "Last-Event-ID": "1"},
    )
    assert first.status_code == 200
    limited = client.get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={**_headers("owner"), "Last-Event-ID": "1"},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "sse_reconnect_rate_limited"
    now += timedelta(seconds=1)
    renewed = client.get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={**_headers("owner"), "Last-Event-ID": "1"},
    )
    assert renewed.status_code == 200


def test_execution_concurrency_quota_and_operator_metrics_are_enforced(client: TestClient) -> None:
    project = _project(client)
    profile = _profile(client)
    _app(client).state.settings.execution_user_concurrent_runs = 1
    _app(client).state.settings.execution_project_concurrent_runs = 1
    agent_session = _session(client, str(project["id"]))
    payload = {
        "gateway_profile_id": profile["id"],
        "content_md": "Bound this pilot turn.",
    }
    accepted = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={**payload, "client_request_id": str(uuid4())},
    )
    assert accepted.status_code == 202, accepted.text
    limited = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={**payload, "client_request_id": str(uuid4())},
    )
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "execution_concurrent_user_quota_exceeded"
    assert limited.headers["Retry-After"] == "1"

    assert client.get("/internal/v1/metrics", headers=_headers("owner")).status_code == 404
    _app(client).state.settings.operator_diagnostics_enabled = True
    _app(client).state.settings.operator_diagnostics_subjects = ["owner"]
    metrics = client.get("/internal/v1/metrics", headers=_headers("owner"))
    assert metrics.status_code == 200
    assert "polycolab_quota_rejections_total" in metrics.text
    assert "sk-pilot-secret" not in metrics.text
    assert client.get("/internal/v1/metrics", headers=_headers("contributor")).status_code == 403


def test_operator_run_diagnostics_are_redacted_audited_and_cross_process_observable(
    client: TestClient,
) -> None:
    project = _project(client)
    profile = _profile(client)
    agent_session = _session(client, str(project["id"]))
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={
            "gateway_profile_id": profile["id"],
            "content_md": "This private prompt must never enter diagnostics.",
            "client_request_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    run_id = UUID(queued.json()["run"]["id"])
    db = _app(client).state.session_factory()
    try:
        claimed = claim_next_run(
            db,
            worker_id="separate-private-worker",
            lease_for=timedelta(minutes=1),
        )
        assert claimed is not None
        running = start_claimed_run(
            db,
            run_id=claimed.id,
            worker_id="separate-private-worker",
            lease_generation=claimed.lease_generation,
        )
        append_worker_event(
            db,
            run_id=running.id,
            worker_id="separate-private-worker",
            lease_generation=running.lease_generation,
            idempotency_key="first-delta",
            kind=AgentRunEventKind.ASSISTANT_DELTA,
            payload={"text": "private output"},
        )
        record_usage(
            db,
            run_id=running.id,
            worker_id="separate-private-worker",
            lease_generation=running.lease_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=3,
            output_tokens=5,
            total_tokens=8,
            idempotency_key="usage",
        )
        finish_run(
            db,
            run_id=running.id,
            worker_id="separate-private-worker",
            lease_generation=running.lease_generation,
            status=AgentRunStatus.FAILED,
            failure_code="model_stream_incomplete",
        )
    finally:
        db.close()

    settings = _app(client).state.settings
    settings.operator_diagnostics_enabled = True
    settings.operator_diagnostics_subjects = ["owner"]
    settings.release_sha = "pilot-release-sha"
    response = client.get(f"/internal/v1/ops/runs/{run_id}", headers=_headers("owner"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["failure_class"] == "provider"
    assert body["agent_kind"] == "RESEARCHER"
    assert body["usage_total_tokens"] == 8
    assert body["release_sha"] == "pilot-release-sha"
    assert body["links"]["metrics"] == "/internal/v1/metrics"
    assert "private prompt" not in response.text
    assert "private output" not in response.text
    assert "separate-private-worker" not in response.text
    denied = client.get(f"/internal/v1/ops/runs/{run_id}", headers=_headers("contributor"))
    assert denied.status_code == 403

    db = _app(client).state.session_factory()
    try:
        audit = db.scalar(
            select(SqlOperatorDiagnosticAccess).where(SqlOperatorDiagnosticAccess.run_id == run_id)
        )
        assert audit is not None
        assert audit.operator_subject_digest != "owner"
        aggregate = db.scalar(
            select(SqlOperationalMetricAggregate).where(
                SqlOperationalMetricAggregate.metric_name == "polycolab_run_terminal_total"
            )
        )
        assert aggregate is not None
    finally:
        db.close()
    metrics_response = client.get("/internal/v1/metrics", headers=_headers("owner"))
    assert metrics_response.status_code == 200
    assert (
        'polycolab_run_terminal_total{agent_kind="RESEARCHER",outcome="FAILED"}'
        in metrics_response.text
    )
    assert "private prompt" not in metrics_response.text
    assert "private output" not in metrics_response.text
    assert "separate-private-worker" not in metrics_response.text


def test_rate_windows_enforce_a_minute_and_roll_over_at_utc_boundary(client: TestClient) -> None:
    db = _app(client).state.session_factory()
    user_id, project_id = uuid4(), uuid4()
    midnight = datetime(2026, 8, 22, 23, 59, 59, tzinfo=UTC)
    try:
        enforce_execution_limits(
            db,
            user_id=user_id,
            project_id=project_id,
            limits=_limits(requests_per_minute=1),
            now=midnight,
        )
        db.commit()
        with pytest.raises(ExecutionLimitExceeded) as error:
            enforce_execution_limits(
                db,
                user_id=user_id,
                project_id=project_id,
                limits=_limits(requests_per_minute=1),
                now=midnight,
            )
        assert error.value.code == "execution_rate_limited"
        db.rollback()
        enforce_execution_limits(
            db,
            user_id=user_id,
            project_id=project_id,
            limits=_limits(requests_per_minute=1),
            now=midnight + timedelta(seconds=1),
        )
        db.commit()
        assert db.query(SqlExecutionRateWindow).count() == 4
    finally:
        db.close()


def test_sse_cursor_anomalies_are_rejected_or_clamped_without_raw_cursor_labels() -> None:
    assert _last_run_cursor("3", 4) == 4
    with pytest.raises(HTTPException):
        _last_run_cursor("bad", 0)
    with pytest.raises(HTTPException):
        _last_session_cursor("-1:0")


def test_sse_connection_gauge_tracks_open_generators_and_closes_without_leaks(
    client: TestClient,
) -> None:
    project = _project(client)
    profile = _profile(client)
    agent_session = _session(client, str(project["id"]))
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={
            "gateway_profile_id": profile["id"],
            "content_md": "Open a stream.",
            "client_request_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    run_id = UUID(queued.json()["run"]["id"])
    db = _app(client).state.session_factory()
    try:
        run = db.get(SqlAgentRun, run_id)
        assert run is not None
        user_id = run.requested_by_user_id
    finally:
        db.close()

    class BlockingRequest:
        def __init__(self, app: FastAPI, released: asyncio.Event) -> None:
            self.app = app
            self._released = released

        async def is_disconnected(self) -> bool:
            await self._released.wait()
            return True

    async def check() -> None:
        released = asyncio.Event()
        streams = [
            _run_event_stream(
                cast(Any, BlockingRequest(_app(client), released)),
                run_id=run_id,
                user_id=user_id,
                cursor=0,
            )
            for _ in range(2)
        ]

        async def next_item(index: int) -> bytes:
            return await anext(streams[index])

        tasks: list[asyncio.Task[bytes]] = [
            asyncio.create_task(next_item(index)) for index in range(len(streams))
        ]
        await asyncio.sleep(0)
        assert metrics.gauge_value("polycolab_sse_connections", service="polycolab-api") >= 2
        released.set()
        for task in tasks:
            with pytest.raises(StopAsyncIteration):
                await task
        assert metrics.gauge_value("polycolab_sse_connections", service="polycolab-api") == 0

    asyncio.run(check())


def test_rate_window_retention_deletes_only_old_rows_in_bounded_batches(client: TestClient) -> None:
    db = _app(client).state.session_factory()
    now = datetime(2026, 8, 22, 12, tzinfo=UTC)
    try:
        db.add_all(
            [
                SqlExecutionRateWindow(
                    scope="user",
                    scope_id=uuid4(),
                    window_started_at=now - timedelta(hours=3),
                    count=1,
                ),
                SqlExecutionRateWindow(
                    scope="project",
                    scope_id=uuid4(),
                    window_started_at=now - timedelta(hours=2),
                    count=1,
                ),
                SqlExecutionRateWindow(
                    scope="user",
                    scope_id=uuid4(),
                    window_started_at=now - timedelta(minutes=30),
                    count=1,
                ),
            ]
        )
        db.commit()
        assert (
            purge_expired_rate_windows(db, retention=timedelta(hours=1), batch_size=1, now=now) == 1
        )
        assert (
            purge_expired_rate_windows(db, retention=timedelta(hours=1), batch_size=10, now=now)
            == 1
        )
        assert db.query(SqlExecutionRateWindow).count() == 1
    finally:
        db.close()


def test_nullable_usage_is_conservatively_aggregated_and_charged(client: TestClient) -> None:
    project = _project(client)
    profile = _profile(client)
    agent_session = _session(client, str(project["id"]))
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={
            "gateway_profile_id": profile["id"],
            "content_md": "Account nullable usage.",
            "client_request_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    db = _app(client).state.session_factory()
    try:
        run_id = UUID(queued.json()["run"]["id"])
        claimed = claim_next_run(db, worker_id="meter", lease_for=timedelta(minutes=1))
        assert claimed is not None
        running = start_claimed_run(
            db, run_id=claimed.id, worker_id="meter", lease_generation=claimed.lease_generation
        )
        record_usage(
            db,
            run_id=running.id,
            worker_id="meter",
            lease_generation=running.lease_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=3,
            output_tokens=None,
            total_tokens=None,
            idempotency_key="nullable-input",
        )
        record_usage(
            db,
            run_id=running.id,
            worker_id="meter",
            lease_generation=running.lease_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=None,
            output_tokens=5,
            total_tokens=None,
            idempotency_key="nullable-output",
        )
        record_usage(
            db,
            run_id=running.id,
            worker_id="meter",
            lease_generation=running.lease_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=None,
            output_tokens=None,
            total_tokens=10,
            idempotency_key="total-only",
        )
        record_usage(
            db,
            run_id=running.id,
            worker_id="meter",
            lease_generation=running.lease_generation,
            source=UsageSource.PROVIDER_REPORTED,
            input_tokens=3,
            output_tokens=5,
            total_tokens=2,
            idempotency_key="inconsistent-total",
        )
        run = db.get(SqlAgentRun, run_id)
        assert run is not None
        tokens, input_tokens, output_tokens, unallocated_tokens = execution_limits._scope_usage(
            db,
            user_id=run.requested_by_user_id,
            project_id=None,
            since=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert (tokens, input_tokens, output_tokens, unallocated_tokens) == (26, 6, 10, 10)
        assert (
            execution_limits._cost_microusd(
                _limits(input_rate=1_000_000, output_rate=2_000_000),
                input_tokens,
                output_tokens,
                unallocated_tokens,
            )
            == 46
        )
        finish_run(
            db,
            run_id=running.id,
            worker_id="meter",
            lease_generation=running.lease_generation,
            status=AgentRunStatus.FAILED,
            failure_code="test_complete",
        )
    finally:
        db.close()


def test_resume_and_next_round_budget_fail_closed_when_ceiling_is_tight(client: TestClient) -> None:
    project = _project(client)
    profile = _profile(client)
    agent_session = _session(client, str(project["id"]))
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=_headers("owner"),
        json={
            "gateway_profile_id": profile["id"],
            "content_md": "Reserve a multi-round turn.",
            "client_request_id": str(uuid4()),
        },
    )
    assert queued.status_code == 202
    run_id = UUID(queued.json()["run"]["id"])
    db = _app(client).state.session_factory()
    try:
        run = db.get(SqlAgentRun, run_id)
        assert run is not None
        tight = _limits(daily_tokens=1, daily_cost=1)
        with pytest.raises(ExecutionLimitExceeded):
            enforce_next_round_budget(db, run=run, limits=tight, now=datetime.now(UTC))
        db.rollback()
    finally:
        db.close()
    assert (
        client.post(f"/api/v1/agent-runs/{run_id}/cancel", headers=_headers("owner")).status_code
        == 202
    )
    _app(client).state.settings.execution_user_daily_tokens = 1
    resumed = client.post(
        f"/api/v1/agent-runs/{run_id}/resume",
        headers=_headers("owner"),
        json={"gateway_profile_id": profile["id"], "client_request_id": str(uuid4())},
    )
    assert resumed.status_code == 429
    assert resumed.json()["error"]["code"] == "execution_daily_token_quota_exceeded"

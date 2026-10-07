from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_version_contracts import snapshot

from polycolab.agents.context import manifest_for_run
from polycolab.agents.runtime.contracts import (
    ModelStreamFrame,
    ModelTurn,
    ToolCallDelta,
    Usage,
)
from polycolab.agents.runtime.gateways import HttpToolGateway, ModelGatewayError
from polycolab.agents.runtime.remote import ApiBackedWorker, HttpRuntimeGateway, RuntimeGatewayError
from polycolab.agents.sessions import (
    append_user_message_and_queue_run,
    archive_agent_session,
    claim_next_run,
    create_agent_session,
    request_cancel,
    start_claimed_run,
)
from polycolab.agents.tools import issue_tool_capability
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlAgentSession,
    SqlGatewayProfile,
    SqlMembership,
    SqlProject,
    SqlRunToolCapability,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    AgentRunEventKind,
    AgentRunStatus,
    PlatformAgentKind,
    ResearchObjectKind,
    WorkspaceRole,
    WorkspaceVisibility,
)
from polycolab.entities.time import utc_now
from polycolab.execution.limits import ExecutionLimits
from polycolab.research.objects import create_object


@dataclass
class FakeModelGateway:
    frames: list[ModelStreamFrame] = field(default_factory=list)
    error: str | None = None
    cancel_after_first: Callable[[], None] | None = None
    turns: list[ModelTurn] = field(default_factory=list)
    grants: list[str] = field(default_factory=list)
    frame_sets: list[list[ModelStreamFrame]] = field(default_factory=list)

    def stream(self, turn: ModelTurn, *, grant: str) -> Iterator[ModelStreamFrame]:
        self.turns.append(turn)
        self.grants.append(grant)
        if self.error is not None:
            raise ModelGatewayError(self.error)
        frames = self.frame_sets.pop(0) if self.frame_sets else self.frames
        for index, frame in enumerate(frames):
            yield frame
            if index == 0 and self.cancel_after_first is not None:
                self.cancel_after_first()


@dataclass
class FakeToolGateway:
    calls: list[dict[str, object]] = field(default_factory=list)

    def call(
        self,
        *,
        capability: str,
        name: str,
        arguments: dict[str, object],
        invocation: str,
        source_event_cursor: int | None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "capability": capability,
                "name": name,
                "arguments": arguments,
                "invocation": invocation,
                "source_event_cursor": source_event_cursor,
            }
        )
        return {"ok": True}


def _queue_run(client: TestClient) -> tuple[Any, UUID, UUID, SqlGatewayProfile]:
    app = cast(Any, client.app)
    session = app.state.session_factory()
    user = SqlUser(issuer="https://issuer.example", subject="runtime-owner", email="runtime@test")
    session.add(user)
    session.commit()
    project = SqlProject(
        name="Runtime project",
        visibility=WorkspaceVisibility.PRIVATE,
        created_by_user_id=user.id,
    )
    profile = SqlGatewayProfile(
        user_id=user.id,
        display_name="runtime profile",
        base_url="https://models.example/v1",
        model_id="runtime-model",
        credential_version=1,
        encrypted_credential=b"not-used-by-fake-gateway",
        wrapped_data_key=b"not-used-by-fake-gateway",
        encryption_key_version="test",
    )
    session.add_all((project, profile))
    session.commit()
    session.add(SqlMembership(project_id=project.id, user_id=user.id, role=WorkspaceRole.OWNER))
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
        content_md="Investigate the induction step.",
    )
    session.close()
    return app, user.id, run.id, profile


class TestRuntimeGateway(HttpRuntimeGateway):
    __test__ = False

    def __init__(self, app: Any) -> None:
        super().__init__("http://testserver", token=app.state.settings.runtime_worker_secret)
        self.client = TestClient(app)

    def _post(self, path: str, payload: dict[str, object]) -> Any:
        response = self.client.post(
            "/internal/v1/runtime" + path, headers=self._headers, json=payload
        )
        if response.status_code not in {200, 204}:
            raise RuntimeGatewayError(
                response.json().get("error", {}).get("code", "runtime_api_failed")
            )
        return response


def _worker(
    app: Any, gateway: FakeModelGateway, tools: FakeToolGateway | None = None
) -> ApiBackedWorker:
    return ApiBackedWorker(
        worker_id="test-builtin-worker",
        runtime_gateway=TestRuntimeGateway(app),
        model_gateway=gateway,
        tool_gateway=tools or FakeToolGateway(),
    )


def test_worker_allows_exact_reservation_then_fails_before_over_budget_round(
    client: TestClient,
) -> None:
    app, _, run_id, _ = _queue_run(client)
    limits = ExecutionLimits(
        user_requests_per_minute=0,
        project_requests_per_minute=0,
        user_concurrent_runs=0,
        project_concurrent_runs=0,
        user_daily_tokens=4,
        project_daily_tokens=4,
        user_daily_cost_microusd=0,
        project_daily_cost_microusd=0,
        input_microusd_per_million_tokens=0,
        output_microusd_per_million_tokens=0,
        max_run_output_tokens=1,
        max_input_tokens_per_round=1,
        max_model_rounds=2,
        max_attempts=1,
    )
    gateway = FakeModelGateway(
        frame_sets=[
            [
                ModelStreamFrame(
                    finish_reason="tool_calls",
                    tool_call_deltas=(ToolCallDelta(index=0, name="get_context", arguments="{}"),),
                ),
                # Inconsistent total is conservatively durable consumption: it
                # leaves insufficient room for a second bounded model round.
                ModelStreamFrame(usage=Usage(completion_tokens=1, prompt_tokens=1, total_tokens=3)),
            ]
        ]
    )
    tools = FakeToolGateway()
    app.state.settings.execution_user_daily_tokens = limits.user_daily_tokens
    app.state.settings.execution_project_daily_tokens = limits.project_daily_tokens
    app.state.settings.execution_max_input_tokens_per_round = 1
    app.state.settings.gateway_max_output_tokens = 1
    app.state.settings.runtime_max_model_rounds = 2
    app.state.settings.runtime_max_attempts = 1
    worker = _worker(app, gateway, tools)

    assert worker.run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        assert (run.status, run.failure_code) == (
            AgentRunStatus.FAILED,
            "execution_run_budget_exceeded",
        )
    finally:
        session.close()
    assert len(gateway.turns) == 1
    assert len(tools.calls) == 1


def _active_capability(client: TestClient) -> tuple[str, UUID]:
    app, _, run_id, _ = _queue_run(client)
    session = app.state.session_factory()
    try:
        claimed = claim_next_run(
            session, worker_id="capability-worker", lease_for=timedelta(seconds=30)
        )
        assert claimed is not None
        running = start_claimed_run(
            session,
            run_id=run_id,
            worker_id="capability-worker",
            lease_generation=claimed.lease_generation,
        )
        manifest = manifest_for_run(session, run=running)
        return (
            issue_tool_capability(
                session,
                run=running,
                manifest=manifest,
                ttl_seconds=30,
                lease_generation=running.lease_generation,
            ),
            run_id,
        )
    finally:
        session.close()


def _internal_tool_call(
    client: TestClient,
    token: str,
    *,
    name: str = "get_context",
    arguments: dict[str, object] | None = None,
    invocation: str | None = None,
    source_cursor: int | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {token}"}
    if invocation is not None:
        headers["X-Polycolab-Tool-Invocation"] = invocation
    if source_cursor is not None:
        headers["X-Polycolab-Source-Event-Cursor"] = str(source_cursor)
    return client.post(
        "/internal/v1/tools/call",
        headers=headers,
        json={"name": name, "arguments": arguments or {}},
    )


def test_builtin_worker_commits_normalized_turn_before_exposing_it(client: TestClient) -> None:
    app, _, run_id, _ = _queue_run(client)
    gateway = FakeModelGateway(
        frames=[
            ModelStreamFrame(content="The base case holds."),
            ModelStreamFrame(finish_reason="stop"),
            ModelStreamFrame(usage=Usage(completion_tokens=5, prompt_tokens=7, total_tokens=12)),
        ]
    )
    worker = _worker(app, gateway)
    assert worker.run_once()
    assert not worker.run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None and run.status is AgentRunStatus.COMPLETED
        events = list(
            session.query(SqlAgentRunEvent)
            .filter(SqlAgentRunEvent.run_id == run_id)
            .order_by(SqlAgentRunEvent.cursor)
        )
        assert [event.kind for event in events] == [
            AgentRunEventKind.RUN_STARTED,
            AgentRunEventKind.ASSISTANT_DELTA,
            AgentRunEventKind.USAGE_REPORTED,
            AgentRunEventKind.ASSISTANT_MESSAGE_COMPLETED,
            AgentRunEventKind.RUN_COMPLETED,
        ]
        messages = list(
            session.query(SqlAgentMessage)
            .filter(SqlAgentMessage.session_id == run.session_id)
            .order_by(SqlAgentMessage.sequence)
        )
        assert messages[-1].content_md == "The base case holds."
        assert gateway.grants[0] not in str([event.payload for event in events])
        assert gateway.turns[0].messages == [
            {"role": "system", "content": "Explore mathematical claims and decompose problems."},
            {"role": "user", "content": "Investigate the induction step."},
        ]
    finally:
        session.close()


def test_builtin_worker_fails_on_profile_rotation_before_private_gateway_call(
    client: TestClient,
) -> None:
    app, _, run_id, profile = _queue_run(client)
    session = app.state.session_factory()
    try:
        stored = session.get(SqlGatewayProfile, profile.id)
        assert stored is not None
        stored.credential_version += 1
        session.commit()
    finally:
        session.close()
    gateway = FakeModelGateway()

    assert _worker(app, gateway).run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        assert (run.status, run.failure_code) == (AgentRunStatus.FAILED, "gateway_profile_changed")
        assert not gateway.turns
    finally:
        session.close()


def test_builtin_worker_observes_current_cancel_and_adapter_replays_canonical_events(
    client: TestClient,
) -> None:
    app, user_id, run_id, profile = _queue_run(client)

    def cancel() -> None:
        session = app.state.session_factory()
        try:
            request_cancel(session, run_id=run_id)
        finally:
            session.close()

    gateway = FakeModelGateway(
        frames=[
            ModelStreamFrame(content="First chunk."),
            ModelStreamFrame(finish_reason="stop"),
            ModelStreamFrame(usage=Usage(completion_tokens=1)),
        ],
        cancel_after_first=cancel,
    )
    worker = _worker(app, gateway)
    assert worker.run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None and run.status is AgentRunStatus.CANCELLED
        agent = session.get(type(run), run_id)
        assert agent is not None
        events = list(
            session.scalars(
                select(SqlAgentRunEvent)
                .where(SqlAgentRunEvent.run_id == run_id)
                .order_by(SqlAgentRunEvent.cursor)
            )
        )
        assert events[-1].kind == AgentRunEventKind.RUN_CANCELLED
    finally:
        session.close()
    del user_id, profile


def test_builtin_worker_rechecks_current_membership_before_model_call(client: TestClient) -> None:
    app, user_id, run_id, _ = _queue_run(client)
    session = app.state.session_factory()
    try:
        membership = session.query(SqlMembership).filter(SqlMembership.user_id == user_id).one()
        session.delete(membership)
        session.commit()
    finally:
        session.close()

    gateway = FakeModelGateway()
    assert not _worker(app, gateway).run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        assert (run.status, run.failure_code) == (AgentRunStatus.FAILED, "authorization_revoked")
        assert not gateway.turns
    finally:
        session.close()


def test_archiving_a_session_cancels_queued_work_before_worker_claim(client: TestClient) -> None:
    app, _, run_id, _ = _queue_run(client)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        archive_agent_session(session, session_id=run.session_id)
        session.refresh(run)
        assert run.status is AgentRunStatus.CANCELLED
    finally:
        session.close()
    gateway = FakeModelGateway()
    assert not _worker(app, gateway).run_once()
    assert not gateway.turns


def test_builtin_worker_normalizes_gateway_errors_without_error_detail(client: TestClient) -> None:
    app, _, run_id, _ = _queue_run(client)
    assert _worker(app, FakeModelGateway(error="provider_unavailable")).run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        assert (run.status, run.failure_code) == (AgentRunStatus.FAILED, "provider_unavailable")
        assert "provider" not in str(run.failure_code).replace("provider_unavailable", "")
    finally:
        session.close()


def test_builtin_worker_completes_a_bounded_redacted_tool_loop(client: TestClient) -> None:
    app, _, run_id, _ = _queue_run(client)
    tools = FakeToolGateway()
    gateway = FakeModelGateway(
        frame_sets=[
            [
                ModelStreamFrame(tool_call_deltas=(ToolCallDelta(index=0, name="get_context"),)),
                ModelStreamFrame(tool_call_deltas=(ToolCallDelta(index=0, arguments="{}"),)),
                ModelStreamFrame(finish_reason="tool_calls"),
                ModelStreamFrame(usage=Usage(completion_tokens=1)),
            ],
            [
                ModelStreamFrame(content="Context inspected."),
                ModelStreamFrame(finish_reason="stop"),
                ModelStreamFrame(usage=Usage(completion_tokens=2)),
            ],
        ]
    )
    worker = _worker(app, gateway, tools)

    assert worker.run_once()
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None and run.status is AgentRunStatus.COMPLETED
        events = list(
            session.query(SqlAgentRunEvent)
            .filter(SqlAgentRunEvent.run_id == run_id)
            .order_by(SqlAgentRunEvent.cursor)
        )
        tool_events = [event for event in events if event.kind.name.startswith("TOOL_")]
        assert [event.kind for event in tool_events] == [
            AgentRunEventKind.TOOL_REQUESTED,
            AgentRunEventKind.TOOL_RESULT,
        ]
        rendered = str([event.payload for event in tool_events])
        assert "arguments" not in rendered and "'ok': True" not in rendered
        assert len(tools.calls) == 1
        invocation = tools.calls[0]["invocation"]
        capability = tools.calls[0]["capability"]
        assert isinstance(invocation, str) and invocation.startswith(f"tool-{run_id}-1-0")
        assert isinstance(capability, str)
        assert capability not in str([event.payload for event in events])
        assert tools.calls[0]["source_event_cursor"] is None
    finally:
        session.close()


def test_concrete_private_tool_gateway_authorizes_and_redacts_capability(
    client: TestClient, monkeypatch: Any
) -> None:
    token, run_id = _active_capability(client)

    def post(_url: str, **kwargs: object) -> Any:
        return client.post(
            "/internal/v1/tools/call",
            headers=cast(dict[str, str], kwargs["headers"]),
            json=cast(dict[str, object], kwargs["json"]),
        )

    monkeypatch.setattr("polycolab.agents.runtime.gateways.httpx.post", post)
    gateway = HttpToolGateway("http://private-api")
    result = gateway.call(
        capability=token,
        name="get_context",
        arguments={},
        invocation=f"tool-{run_id}-1-0",
        source_event_cursor=None,
    )
    assert "object_versions" in result
    assert token not in repr(result)
    with pytest.raises(Exception, match="tool_authorization_denied"):
        gateway.call(
            capability=token,
            name="submit_proposal",
            arguments={"summary": "x", "changes": []},
            invocation=f"tool-{run_id}-1-1",
            source_event_cursor=None,
        )


@pytest.mark.parametrize(
    "state",
    ["expired", "revoked", "membership_removed", "session_archived", "terminal", "stale_lease"],
)
def test_internal_tool_gateway_denies_current_capability_lifecycle_state(
    client: TestClient, state: str
) -> None:
    token, run_id = _active_capability(client)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        capability = session.scalar(
            select(SqlRunToolCapability).where(
                SqlRunToolCapability.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert run is not None and capability is not None
        if state == "expired":
            capability.expires_at = utc_now() - timedelta(seconds=1)
        elif state == "revoked":
            capability.revoked = True
        elif state == "membership_removed":
            membership = (
                session.query(SqlMembership)
                .filter(SqlMembership.user_id == run.requested_by_user_id)
                .one()
            )
            session.delete(membership)
        elif state == "session_archived":
            archive_agent_session(session, session_id=run.session_id)
            return_response = _internal_tool_call(client, token)
            assert return_response.status_code == 401
            return
        elif state == "terminal":
            run.status = AgentRunStatus.COMPLETED
        else:
            run.lease_generation += 1
        session.commit()
    finally:
        session.close()
    assert _internal_tool_call(client, token).status_code == 401


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("get_context", {"extra": True}),
        ("get_object_revision", {}),
        ("get_object_revision", {"revision_id": "not-a-uuid"}),
        ("get_dependencies", {"revision_id": "not-a-uuid", "extra": True}),
        ("submit_proposal", {"summary": "x", "changes": "not-an-array"}),
        (
            "submit_proposal",
            {"summary": "x", "changes": [], "source_event_cursors": [1]},
        ),
    ],
)
def test_internal_tool_gateway_rejects_every_fixed_tool_malformed_arguments(
    client: TestClient, name: str, arguments: dict[str, object]
) -> None:
    token, _ = _active_capability(client)
    assert _internal_tool_call(client, token, name=name, arguments=arguments).status_code == 401


def test_internal_tool_gateway_rejects_private_creator_scope_mismatch(
    client: TestClient,
) -> None:
    token, run_id = _active_capability(client)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        other = SqlUser(
            issuer="https://issuer.example", subject="other-private-owner", email="other@test"
        )
        session.add(other)
        session.flush()
        parent = session.get(SqlAgentSession, run.session_id)
        assert parent is not None
        parent.created_by_user_id = other.id
        session.commit()
    finally:
        session.close()
    assert _internal_tool_call(client, token).status_code == 401


def test_internal_tool_gateway_rejects_capability_session_and_tool_scope_mismatch(
    client: TestClient,
) -> None:
    token, run_id = _active_capability(client)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        capability = session.scalar(
            select(SqlRunToolCapability).where(
                SqlRunToolCapability.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert run is not None and capability is not None
        other_session = create_agent_session(
            session,
            project_id=run.project_id,
            created_by_user_id=run.requested_by_user_id,
            agent_kind=PlatformAgentKind.CRITIC,
        )
        capability.allowed_tools = []
        session.commit()
    finally:
        session.close()
    assert _internal_tool_call(client, token).status_code == 401
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        capability = session.scalar(
            select(SqlRunToolCapability).where(
                SqlRunToolCapability.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert run is not None and capability is not None
        capability.allowed_tools = ["get_context"]
        capability.session_id = other_session.id
        session.commit()
    finally:
        session.close()
    assert _internal_tool_call(client, token).status_code == 401


def test_internal_tool_gateway_rejects_cross_project_revision_reference(client: TestClient) -> None:
    from polycolab.workspaces.service import create_workspace

    token, run_id = _active_capability(client)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        user = session.get(SqlUser, run.requested_by_user_id)
        assert user is not None
        project = create_workspace(
            SqlAlchemyTransaction(session),
            name="Other project",
            description=None,
            visibility=WorkspaceVisibility.PRIVATE,
            creator=user,
        )
        _, revision = create_object(
            session,
            project_id=project.id,
            kind=ResearchObjectKind.CLAIM,
            title="Outside context",
            content_md="private",
            rationale=None,
            author=user,
        )
    finally:
        session.close()
    response = _internal_tool_call(
        client,
        token,
        name="get_object_revision",
        arguments={"revision_id": str(revision.id)},
    )
    assert response.status_code == 401


def test_internal_tool_gateway_rejects_prior_submit_event_not_bound_to_invocation(
    client: TestClient,
) -> None:
    token, run_id = _active_capability(client)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        cursor = run.next_event_cursor + 1
        session.add(
            SqlAgentRunEvent(
                run_id=run.id,
                cursor=cursor,
                idempotency_key="prior-submit-requested",
                kind=AgentRunEventKind.TOOL_REQUESTED,
                payload={"tool_name": "submit_proposal"},
            )
        )
        session.commit()
    finally:
        session.close()
    response = _internal_tool_call(
        client,
        token,
        name="submit_proposal",
        arguments={
            "summary": "A claim",
            "changes": [{"kind": "CREATE_OBJECT", "snapshot": snapshot()}],
        },
        invocation="current-submit",
        source_cursor=cursor,
    )
    assert response.status_code == 401

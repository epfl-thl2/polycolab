"""Host/Codex contract tests; never starts Codex, a VM, or a model provider."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from polycolab.agents.runtime.codex import CodexFailure, CodexSession, CodexTask, decode_frame
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.db.models import SqlAgentRun, SqlAgentRunUsage
from polycolab.execution.microsandbox import GuestChannel, ImagePolicy, MicrosandboxRuntime
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.model_gateway.responses import completed_response, validated_request
from polycolab.model_gateway.service import ProviderFailure
from polycolab.model_gateway.transport import ProviderStreamResponse
from polycolab.verification.contracts import ResourceLimits


def spec() -> RuntimeSpec:
    return RuntimeSpec(
        image="registry.example/agent@sha256:" + "a" * 64,
        limits=ResourceLimits(
            cpu_count=1,
            cpu_seconds=60,
            wall_seconds=60,
            memory_bytes=1024**3,
            process_count=64,
            disk_bytes=1024**3,
            log_bytes=1024**2,
            output_bytes=1024**2,
            output_files=64,
        ),
    )


class Channel:
    def __init__(self, notifications: list[dict[str, Any]]) -> None:
        self.frames = deque(
            [
                {"id": 1, "result": {}},
                {"id": 2, "result": {"thread": {"id": "private-thread"}}},
                {"id": 3, "result": {"turn": {"id": "private-turn"}}},
                *notifications,
            ]
        )
        self.sent: list[dict[str, object]] = []

    async def send(self, frame: dict[str, object]) -> None:
        self.sent.append(frame)

    async def receive(self) -> dict[str, object]:
        if not self.frames:
            raise CodexFailure("codex_stream_incomplete")
        return self.frames.popleft()


def notification(method: str, **params: object) -> dict[str, object]:
    return {
        "method": method,
        "params": {
            "threadId": "private-thread",
            "turnId": "private-turn",
            **params,
        },
    }


def terminal() -> dict[str, object]:
    return notification("turn/completed", turn={"id": "private-turn", "status": "completed"})


def run_codex(
    frames: list[dict[str, Any]], *, max_calls: int = 16
) -> tuple[str, list[Any], list[Any], Channel]:
    channel = Channel(frames)
    events: list[Any] = []
    calls: list[Any] = []

    async def event(key: str, kind: str, payload: dict[str, object]) -> int:
        events.append((key, kind, payload))
        return len(events)

    async def tool(
        name: str, arguments: dict[str, object], invocation: str, cursor: int
    ) -> dict[str, object]:
        calls.append((name, arguments, invocation, cursor))
        return {"content": "private result"}

    task = CodexTask(
        "test-model",
        [
            {"role": "system", "content": "Research carefully."},
            {"role": "user", "content": "Prove the claim."},
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "submit_proposal",
                    "description": "Submit for review.",
                    "parameters": {"type": "object"},
                },
            }
        ],
        max_tool_calls=max_calls,
    )
    return asyncio.run(CodexSession(channel, task, event, tool).run()), events, calls, channel


def test_codex_streams_text_and_dispatches_only_host_scoped_tools() -> None:
    frames = [
        notification("item/reasoning/textDelta", delta="private reasoning"),
        notification("thread/tokenUsage/updated", tokenUsage={"total": 99999}),
        {
            **notification(
                "item/tool/call",
                tool="submit_proposal",
                arguments={"summary": "draft"},
                callId="guest-selected-id",
            ),
            "id": 42,
        },
        notification("item/agentMessage/delta", delta="A result."),
        terminal(),
    ]
    text, events, calls, channel = run_codex(frames)
    assert text == "A result."
    assert calls == [("submit_proposal", {"summary": "draft"}, "tool-1", 1)]
    assert [event[1] for event in events] == ["TOOL_REQUESTED", "TOOL_RESULT", "ASSISTANT_DELTA"]
    serialized = json.dumps(events)
    for private in ("private reasoning", "private result", "guest-selected-id", "99999", "draft"):
        assert private not in serialized
    assert channel.sent[-1]["id"] == 42
    start = next(item for item in channel.sent if item.get("method") == "thread/start")
    assert isinstance(start["params"], dict)
    assert start["params"]["ephemeral"] is True


def test_codex_shell_history_omits_commands_output_and_paths() -> None:
    item = {
        "id": "shell1",
        "type": "commandExecution",
        "command": "private command",
        "aggregatedOutput": "private stdout",
        "status": "completed",
    }
    _, events, _, _ = run_codex(
        [
            notification("item/started", item=item),
            notification("item/completed", item=item),
            notification("item/agentMessage/delta", delta="Done."),
            terminal(),
        ]
    )
    assert events[0][2]["tool_name"] == "shell"
    assert "private" not in json.dumps(events)


@pytest.mark.parametrize(
    "frame,code",
    [
        (
            {
                **notification("item/tool/call", tool="exec_host", arguments={}, callId="x"),
                "id": 99,
            },
            "codex_tool_invalid",
        ),
        (
            {**notification("item/tool/call", tool=["bad"], arguments={}, callId="x"), "id": 99},
            "codex_tool_invalid",
        ),
        (
            {**notification("item/commandExecution/requestApproval"), "id": 99},
            "codex_request_unsupported",
        ),
        (
            notification("item/agentMessage/delta", threadId="another-thread", delta="leak"),
            "codex_thread_mismatch",
        ),
        (
            notification(
                "turn/completed",
                turn={"id": "private-turn", "status": "failed", "error": "sensitive detail"},
            ),
            "codex_turn_failed",
        ),
    ],
)
def test_codex_rejects_untrusted_protocol_fields(frame: dict[str, Any], code: str) -> None:
    with pytest.raises(CodexFailure, match=f"^{code}$"):
        run_codex([frame])


def test_codex_bounds_tools_and_requires_terminal() -> None:
    with pytest.raises(CodexFailure, match="tool_call_limit_exceeded"):
        run_codex(
            [notification("item/started", item={"id": "a", "type": "commandExecution"})],
            max_calls=0,
        )
    with pytest.raises(CodexFailure, match="codex_stream_incomplete"):
        run_codex([notification("item/agentMessage/delta", delta="incomplete")])
    with pytest.raises(CodexFailure, match="codex_frame_too_large"):
        decode_frame(b"x" * 1_000_001)


def test_microsandbox_gate_precedes_sdk_and_host_access(tmp_path: Path) -> None:
    runtime = MicrosandboxRuntime(tmp_path / "not-created")
    with pytest.raises(
        SandboxUnavailable, match="linux_microsandbox_required|executor_service_required"
    ):
        asyncio.run(runtime.reconcile())
    assert not (tmp_path / "not-created").exists()


def test_curated_image_requires_digest() -> None:
    with pytest.raises(ValueError):
        ImagePolicy("python:latest", "PYTHON", "3.14", "a" * 64, "b" * 64, "linux/amd64")


def response_bytes(output_tokens: int = 3) -> bytes:
    return (
        "event: response.completed\ndata: "
        + json.dumps(
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "usage": {
                        "input_tokens": 4,
                        "output_tokens": output_tokens,
                        "total_tokens": 4 + output_tokens,
                    },
                },
            }
        )
        + "\n\n"
    ).encode()


@pytest.mark.parametrize(
    "change",
    [
        {"model": "another-model"},
        {"store": True},
        {"background": True},
        {"tools": [{"type": "web_search"}]},
        {"previous_response_id": "other-run"},
        {"input": [{"type": "input_file", "file_url": "http://private"}]},
    ],
)
def test_responses_rejects_remote_side_effects_and_cross_run_references(
    change: dict[str, Any],
) -> None:
    with pytest.raises(ProviderFailure):
        validated_request(
            {"model": "test", "stream": True, "input": "hello", **change},
            model="test",
            max_output_tokens=10,
            max_input_bytes=1000,
        )


def test_responses_terminal_usage_and_bounds() -> None:
    data, usage = completed_response([response_bytes()], max_bytes=1000, max_output_tokens=10)
    assert usage == {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7}
    assert data == response_bytes()
    for chunks in ([response_bytes()[:-1]], [response_bytes(11)], [b"data: {}\n\n"]):
        with pytest.raises(ProviderFailure):
            completed_response(chunks, max_bytes=1000, max_output_tokens=10)


def test_guest_model_bridge_does_not_accept_duplicate_requests() -> None:
    class Process:
        frames = deque(
            [
                json.dumps(
                    {
                        "kind": "model",
                        "payload": {
                            "id": 1,
                            "body": {"model": "test"},
                        },
                    }
                ).encode()
            ]
            * 2
        )

        async def receive(self) -> bytes:
            return self.frames.popleft()

        async def send(self, data: bytes) -> None:
            assert b"response.completed" not in data  # Binary-safe encoding.

        async def wait(self) -> int:
            return 0

    requests = []

    async def model(body: dict[str, object]) -> bytes:
        requests.append(body)
        return response_bytes()

    with pytest.raises(CodexFailure, match="codex_protocol_invalid"):
        asyncio.run(GuestChannel(Process(), model, 4).receive())
    assert len(requests) == 1


@pytest.mark.parametrize("provider_fails", [False, True])
@pytest.mark.parametrize("lose_lease", [False, True])
def test_private_responses_broker_records_provider_usage(
    client: TestClient, monkeypatch: Any, provider_fails: bool, lose_lease: bool
) -> None:
    from test_runtime_api import _queue_run

    app, run_id = _queue_run(client)
    session = app.state.session_factory()
    row = session.get(SqlAgentRun, run_id)
    row.runtime_spec = spec().model_dump(mode="json")
    from datetime import UTC, datetime, timedelta

    from polycolab.execution.allocator import admit

    row.deadline_at = datetime.now(UTC) + timedelta(seconds=60)
    admit(session, row)
    session.commit()
    session.close()
    headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    legacy = client.post(
        "/internal/v1/runtime/claims",
        headers=headers,
        json={"worker_id": "legacy", "engine": "builtin"},
    )
    assert legacy.status_code == 204
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers=headers,
        json={"worker_id": "codex", "engine": "codex"},
    ).json()
    assert claim["tools"]
    requests = []

    class Provider:
        async def __call__(self, **kwargs: Any) -> bytes:
            requests.append(kwargs)
            if lose_lease:
                with app.state.session_factory() as db:
                    run = db.get(SqlAgentRun, run_id)
                    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    db.commit()
            if provider_fails:
                from polycolab.model_gateway.transport import ProviderTransportError

                raise ProviderTransportError("provider_request_uncertain")
            return response_bytes()

    monkeypatch.setattr(
        "polycolab.model_gateway.hosted.decrypt_credential", lambda *a, **k: "test-key"
    )
    app.state.hosted_provider_transport = Provider()
    result = client.post(
        f"/internal/v1/runtime/runs/{run_id}/responses",
        headers=headers,
        json={
            "worker_id": "codex",
            "request_id": "model-1",
            "lease_generation": claim["lease_generation"],
            "body": {"model": claim["model_id"], "stream": True, "input": "hello"},
        },
    )
    assert result.status_code == (409 if provider_fails or lose_lease else 200), result.text
    session = app.state.session_factory()
    usage = session.scalar(select(SqlAgentRunUsage).where(SqlAgentRunUsage.run_id == run_id))
    assert usage is not None
    expected = spec().max_input_tokens + spec().max_output_tokens if provider_fails else 7
    assert usage.total_tokens == expected
    assert usage.source.value == ("ESTIMATED" if provider_fails else "PROVIDER_REPORTED")
    assert requests[0]["payload"]["store"] is False
    assert "test-key" not in result.text
    duplicate = client.post(
        f"/internal/v1/runtime/runs/{run_id}/responses",
        headers=headers,
        json={
            "worker_id": "codex",
            "request_id": "model-1",
            "lease_generation": claim["lease_generation"],
            "body": {"model": claim["model_id"], "stream": True, "input": "hello"},
        },
    )
    assert duplicate.status_code == 409
    assert len(requests) == 1
    session.close()


def test_controller_state_excludes_a_second_process(tmp_path: Path) -> None:
    from polycolab.execution.service import exclusive_controller_state

    root = tmp_path / "state"
    with exclusive_controller_state(root):
        with pytest.raises(BlockingIOError), exclusive_controller_state(root):
            pytest.fail("a second controller acquired the same state")
    with exclusive_controller_state(root):
        pass


@pytest.mark.parametrize("stop_fails", [False, True])
def test_attempt_cleanup_confirms_death_before_removing_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stop_fails: bool
) -> None:
    import sys
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    calls: list[str] = []
    creation: dict[str, Any] = {}

    class FakeSandbox:
        @staticmethod
        async def create(name: str, **kwargs: Any) -> FakeSandbox:
            creation.update(kwargs)
            calls.append("create")
            return FakeSandbox()

        async def kill(self, **kwargs: Any) -> None:
            calls.append("kill")
            if stop_fails:
                raise RuntimeError("private SDK diagnostic")

        async def wait_until_stopped(self) -> None:
            calls.append("stopped")

        @staticmethod
        async def remove(name: str) -> None:
            calls.append("remove")

    fake_sdk = SimpleNamespace(
        Sandbox=FakeSandbox,
        Image=SimpleNamespace(oci=lambda *args, **kwargs: args[0]),
        RootDisk=SimpleNamespace(managed=lambda value: value),
        Network=SimpleNamespace(none=lambda: "offline"),
        PullPolicy=SimpleNamespace(NEVER="never"),
        SecurityProfile=SimpleNamespace(RESTRICTED="restricted"),
        MountKind=SimpleNamespace(BIND="bind"),
        MountConfig=lambda **kwargs: kwargs,
    )
    monkeypatch.setitem(sys.modules, "microsandbox", fake_sdk)
    monkeypatch.setattr("polycolab.execution.microsandbox.version", lambda _: "0.6.18")

    class FakeAcceptedRuntime(MicrosandboxRuntime):
        async def check_ready(self) -> None:
            pass

    runtime = FakeAcceptedRuntime(tmp_path / "state")
    image = ImagePolicy(spec().image, "AGENT", "0.154.0", "b" * 64, "c" * 64, "test")

    async def exercise() -> None:
        async with runtime.attempt(
            name="test-attempt",
            image=image,
            limits=spec().limits,
            deadline=datetime.now(UTC) + timedelta(seconds=60),
            inputs={"source.py": b"print(42)"},
        ) as (_sandbox, output):
            assert (output.parent / "inputs/source.py").read_bytes() == b"print(42)"
            raise asyncio.CancelledError

    if stop_fails:
        with pytest.raises(SandboxUnavailable, match="^sandbox_cleanup_unconfirmed$"):
            asyncio.run(exercise())
        assert calls == ["create", "kill"]
        assert list(runtime.state_dir.glob("attempt-*"))
    else:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(exercise())
        assert calls == ["create", "kill", "stopped", "remove"]
        assert not list(runtime.state_dir.glob("attempt-*"))
    assert creation["network"] == "offline"
    assert creation["pull_policy"] == "never"
    assert creation["security"] == "restricted"
    assert creation["user"] == "1000"
    assert creation["volumes"]["/inputs"]["readonly"] is True
    assert creation["labels"]["controller"] == runtime.owner


def test_new_profile_validation_uses_responses(client: TestClient) -> None:
    from typing import cast

    from fastapi import FastAPI

    requests: list[dict[str, Any]] = []

    class Provider:
        def open_stream(self, **kwargs: Any) -> ProviderStreamResponse:
            requests.append(kwargs)
            return ProviderStreamResponse(200, iter([response_bytes()]), lambda: None)

    app = cast(FastAPI, client.app)
    app.state.provider_transport = Provider()
    headers = {"Authorization": "Bearer owner"}
    profile = client.post(
        "/api/v1/gateway/profiles",
        headers=headers,
        json={
            "display_name": "Responses",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "test",
            "api_key": "test-private-key",
        },
    )
    assert profile.status_code == 201
    assert profile.json()["wire_api"] == "responses"
    result = client.post(
        f"/api/v1/gateway/profiles/{profile.json()['id']}/validate", headers=headers
    )
    assert result.status_code == 200
    assert len(requests) == 1
    assert requests[0]["responses"] is True
    assert requests[0]["payload"]["store"] is False
    assert "test-private-key" not in result.text


def test_turn_notifications_can_precede_start_response(monkeypatch: pytest.MonkeyPatch) -> None:
    original = Channel.__init__

    def interleaved(self: Channel, notifications: list[dict[str, Any]]) -> None:
        original(self, notifications)
        frames = list(self.frames)
        self.frames = deque([*frames[:2], *frames[3:], frames[2]])

    monkeypatch.setattr(Channel, "__init__", interleaved)
    result, _, _, _ = run_codex(
        [notification("item/agentMessage/delta", delta="Done."), terminal()]
    )
    assert result == "Done."


@pytest.mark.parametrize(
    "provider_error", [None, "provider_rejected", "provider_request_uncertain"]
)
@pytest.mark.parametrize("with_repository", [False, True])
def test_hosted_controller_stops_before_collecting_only_declared_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_error: str | None,
    with_repository: bool,
) -> None:
    from contextlib import asynccontextmanager
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from polycolab.agents.runtime.controller import AgentController
    from polycolab.agents.runtime.remote import RuntimeClaim

    actions: list[str] = []
    output = tmp_path / "outputs"
    output.mkdir()
    (output / "result.txt").write_bytes(b"result")
    (output / "unregistered.txt").write_bytes(b"private scratch")

    @asynccontextmanager
    async def attempt(**kwargs: Any) -> Any:
        yield object(), output
        actions.append("slot-returned")

    async def stopped(*args: Any) -> None:
        actions.append("stopped")

    def codex(channel: Any, task: Any, event: Any, tool: Any) -> Any:
        async def answer() -> str:
            if provider_error:
                from polycolab.agents.runtime.remote import RuntimeGatewayError

                raise RuntimeGatewayError(provider_error)
            await tool("export_artifact", {"path": "result.txt", "display_name": "Result"}, "1", 1)
            return "Done."

        return SimpleNamespace(run=answer)

    monkeypatch.setattr("polycolab.agents.runtime.controller.CodexSession", codex)

    async def checkpoint() -> None:
        actions.append("checkpoint")
        (output / "workspace.bundle").write_bytes(b"repository bundle")

    monkeypatch.setattr(
        "polycolab.agents.runtime.controller.GuestChannel",
        lambda *args: SimpleNamespace(checkpoint_repository=checkpoint),
    )
    gateway = AsyncMock()
    gateway.save_repository.side_effect = lambda *args: actions.append("repository-saved")
    gateway.inputs.return_value = {}
    gateway.lease.return_value = {"active": True}
    gateway.export.side_effect = lambda *args: actions.append("uploaded")
    image = ImagePolicy(spec().image, "AGENT", "0.154.0", "b" * 64, "c" * 64, "test")
    runtime = SimpleNamespace(
        images={spec().image.rsplit(":", 1)[-1]: image},
        agent=attempt,
        stop_agent=stopped,
        acknowledge=lambda *args: None,
    )
    claim = RuntimeClaim(
        run_id=uuid4(),
        lease_generation=1,
        model_id="model",
        messages=[],
        tool_capability="private",
        max_output_tokens=100,
        max_model_rounds=4,
        max_tool_calls=16,
        max_tool_argument_bytes=1000,
        max_tool_result_bytes=1000,
        lease_for=timedelta(seconds=30),
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
        runtime_spec=spec().model_dump(mode="json"),
    )
    if with_repository:
        from dataclasses import replace

        claim = replace(claim, repository={"branch": f"sessions/{uuid4()}", "commit": "a" * 40})
    asyncio.run(AgentController(gateway, runtime, "hosted").execute(claim))  # type: ignore[arg-type]
    if provider_error:
        gateway.export.assert_not_awaited()
        gateway.save_repository.assert_not_awaited()
        finish = gateway.lease.call_args.kwargs
        assert finish["status"] == "FAILED"
        assert finish["failure_code"] == (
            "provider_uncertain_resume_required"
            if provider_error == "provider_request_uncertain"
            else provider_error
        )
        return
    assert actions == (
        ["checkpoint", "stopped", "slot-returned", "uploaded", "repository-saved"]
        if with_repository
        else ["stopped", "slot-returned", "uploaded"]
    )
    if with_repository:
        gateway.save_repository.assert_awaited_once()
        assert gateway.save_repository.call_args.args[-1] == b"repository bundle"
    gateway.export.assert_awaited_once()
    assert gateway.export.call_args.args[-1] == b"result"

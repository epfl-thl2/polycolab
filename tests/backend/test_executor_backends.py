"""Backend identity, offline launch policy and failure-boundary regressions."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from test_codex_runtime import spec

from polycolab.agents.runtime.client import RuntimeClient
from polycolab.agents.runtime.codex import CodexFailure, decode_frame
from polycolab.agents.runtime.remote import RuntimeGatewayError
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.execution.docker import DockerRuntime
from polycolab.execution.runtime import ImagePolicy, SlotQuarantined
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.execution.service import ServiceConfig, make_runtime


def runtime(path: Path) -> DockerRuntime:
    image = ImagePolicy(spec().image, "AGENT", "0.154.0", "a" * 64, "b" * 64, "linux-x86_64")
    return DockerRuntime(
        path,
        (image,),
        1,
        version="release-20261005.0",
        socket="/run/test-docker.sock",
        helper="/usr/local/libexec/test-helper",
        runtime_name="polycolab-runsc",
    )


def test_old_specs_keep_microsandbox_identity() -> None:
    value = spec().model_dump()
    value.pop("sandbox_backend")
    assert RuntimeSpec.model_validate(value).sandbox_backend == "microsandbox"
    config = ServiceConfig(api_url="http://localhost")
    assert make_runtime(config).backend == "microsandbox"
    config = config.model_copy(
        update={"backend": "gvisor", "sandbox_version": "release-20261005.0"}
    )
    assert make_runtime(config).backend == "gvisor"


def test_guest_frame_rejects_escaped_invalid_unicode() -> None:
    with pytest.raises(CodexFailure, match="codex_protocol_invalid"):
        decode_frame(b'{"delta":"\\ud800"}')


@pytest.mark.parametrize("name,write", [("get_context", False), ("write_summary", True)])
def test_tool_provenance_only_on_writes(name: str, write: bool) -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert ("x-polycolab-source-event-cursor" in request.headers) is write
            assert request.headers["authorization"] == "Bearer scoped"
            return httpx.Response(200, json={})

        client = RuntimeClient(
            "http://localhost", "private", transport=httpx.MockTransport(handler)
        )
        try:
            claim: Any = SimpleNamespace(tool_capability="scoped")
            assert await client.tool(claim, name, {}, "invocation", 1) == {}
        finally:
            await client.close()

    asyncio.run(scenario())


def test_malformed_claim_is_a_run_transport_error() -> None:
    async def scenario() -> None:
        client = RuntimeClient(
            "http://localhost",
            "private",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"run_id": "invalid"})
            ),
        )
        try:
            with pytest.raises(RuntimeGatewayError, match="runtime_api_invalid"):
                await client.claim("worker")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_docker_launch_policy_has_no_ambient_authority(tmp_path: Path) -> None:
    adapter = runtime(tmp_path)
    image = next(iter(adapter.images.values()))
    args = adapter.create_args(
        "a" * 32, tmp_path / "work", image, spec().limits, datetime.now(UTC) + timedelta(seconds=60)
    )
    for required in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--pull=never",
        "--restart=no",
        "--log-driver=none",
        "--ipc=none",
    ):
        assert required in args
    assert "--privileged" not in args
    mounts = [args[i + 1] for i, arg in enumerate(args) if arg == "--mount"]
    assert any("dst=/inputs,readonly" in mount for mount in mounts)
    assert all("docker.sock" not in mount and "repositories" not in mount for mount in mounts)
    assert adapter.docker_args("ps")[:3] == ("docker", "--host", "unix:///run/test-docker.sock")
    assert "DOCKER_CONTEXT" not in adapter.environment


def test_failed_launch_with_uncertain_cleanup_quarantines_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = runtime(tmp_path)
    slot = tmp_path / "slots" / "0"
    slot.mkdir(parents=True)
    work = slot / "work"
    work.mkdir()
    monkeypatch.setattr(adapter, "prepare_files", lambda *args: work)
    monkeypatch.setattr(adapter, "host", AsyncMock(side_effect=SandboxUnavailable("daemon_down")))

    async def scenario() -> None:
        async with adapter.reserve():
            with pytest.raises(SlotQuarantined):
                async with adapter.agent(
                    name="job",
                    image=next(iter(adapter.images.values())),
                    limits=spec().limits,
                    deadline=datetime.now(UTC) + timedelta(seconds=120),
                    inputs={},
                    run_id="test-run",
                    generation=1,
                    worker_id="test-worker",
                ):
                    pytest.fail("failed launch must not yield")
        assert adapter.states == {0: "QUARANTINED"}
        async with adapter.reserve() as slot_id:
            assert slot_id is None
        journals = list((tmp_path / "attempts").glob("*.json"))
        assert len(journals) == 1
        deadline = datetime.fromisoformat(json.loads(journals[0].read_text())["deadline"])
        assert (deadline - datetime.now(UTC)).total_seconds() <= spec().limits.wall_seconds

    asyncio.run(scenario())


def test_cleanup_keeps_outputs_until_stopped_and_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = runtime(tmp_path)
    slot = tmp_path / "slots" / "0"
    work = slot / "work"
    work.mkdir(parents=True)
    (work / "private").write_bytes(b"scratch")
    events: list[str] = []

    async def stop(attempt: str) -> None:
        assert (work / "private").exists()
        events.append("stop")

    async def docker(*args: str) -> bytes:
        assert events == ["stop"] and work.exists()
        events.append("remove")
        return b""

    async def host(*args: str) -> bytes:
        assert events == ["stop", "remove"] and work.exists()
        events.append("release")
        return b""

    monkeypatch.setattr(adapter, "stop", stop)
    monkeypatch.setattr(
        adapter, "inspect_owned", AsyncMock(return_value={"State": {"Running": False}})
    )
    monkeypatch.setattr(adapter, "docker", docker)
    monkeypatch.setattr(adapter, "host", host)
    asyncio.run(adapter.cleanup("a" * 32, slot))
    assert events == ["stop", "remove", "release"]
    assert not work.exists()


def test_reconciliation_does_not_prune_unknown_owned_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = runtime(tmp_path)
    monkeypatch.setattr(adapter, "check_ready", AsyncMock())
    docker = AsyncMock(return_value=b"polycolab-exec-unknown\n")
    monkeypatch.setattr(adapter, "docker", docker)
    with pytest.raises(SandboxUnavailable, match="owned_container_without_journal"):
        asyncio.run(adapter.reconcile())
    assert docker.await_count == 1


def test_reconciliation_rejects_backend_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = runtime(tmp_path)
    folder = tmp_path / "attempts"
    folder.mkdir()
    (folder / ("a" * 32 + ".json")).write_text(json.dumps({"backend": "microsandbox"}))
    monkeypatch.setattr(adapter, "check_ready", AsyncMock())
    monkeypatch.setattr(adapter, "docker", AsyncMock(return_value=b""))
    with pytest.raises(SandboxUnavailable, match="journal_backend_mismatch"):
        asyncio.run(adapter.reconcile())


def test_created_container_cleanup_does_not_wait_for_a_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = runtime(tmp_path)
    monkeypatch.setattr(adapter, "host", AsyncMock())
    monkeypatch.setattr(
        adapter,
        "inspect_owned",
        AsyncMock(return_value={"State": {"Running": False, "Status": "created"}}),
    )
    docker = AsyncMock()
    monkeypatch.setattr(adapter, "docker", docker)
    asyncio.run(adapter.stop("a" * 32))
    docker.assert_not_awaited()


def test_reconcile_retired_slot_before_capacity_reduction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = runtime(tmp_path)
    folder = tmp_path / "attempts"
    folder.mkdir()
    attempt = "a" * 32
    row = {"backend": "gvisor", "container": "polycolab-exec-" + attempt, "slot_id": 3}
    (folder / (attempt + ".json")).write_text(json.dumps(row))
    monkeypatch.setattr(adapter, "check_ready", AsyncMock())
    monkeypatch.setattr(adapter, "docker", AsyncMock(return_value=b""))
    cleanup = AsyncMock()
    monkeypatch.setattr(adapter, "cleanup", cleanup)
    asyncio.run(adapter.reconcile())
    cleanup.assert_awaited_once_with(attempt, tmp_path / "slots" / "3")
    assert adapter.terminated == [row]
    assert adapter.states == {0: "AVAILABLE"}


def test_blocking_filesystem_work_does_not_block_heartbeat_and_is_joined() -> None:
    import threading

    from polycolab.execution.host_io import blocking

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def filesystem() -> None:
        entered.set()
        assert release.wait(timeout=5)
        finished.set()

    async def scenario() -> None:
        task = asyncio.create_task(blocking(filesystem))
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(scenario())


def test_delayed_claim_response_reduces_lease_without_false_clock_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uuid import uuid4

    from polycolab.agents.runtime import client as module

    sent = datetime.now(UTC)
    times = iter([sent, sent + timedelta(seconds=10)])

    class Clock:
        @staticmethod
        def now(*_: object) -> datetime:
            return next(times)

    monkeypatch.setattr(module, "datetime", Clock)

    async def scenario() -> None:
        client = RuntimeClient("http://localhost", "private")

        async def post(*_: object, **__: object) -> dict[str, object]:
            await asyncio.sleep(0.01)
            return {
                "run_id": str(uuid4()),
                "lease_generation": 1,
                "model_id": "test",
                "messages": [],
                "tool_capability": "scoped",
                "max_output_tokens": 100,
                "max_model_rounds": 4,
                "max_tool_calls": 4,
                "max_tool_argument_bytes": 100,
                "max_tool_result_bytes": 100,
                "lease_seconds": 30,
                "deadline_at": (sent + timedelta(seconds=60)).isoformat(),
                "runtime_spec": spec().model_dump(mode="json"),
                "tools": [],
                "server_time": (sent + timedelta(seconds=1)).isoformat(),
            }

        monkeypatch.setattr(client, "post", post)
        try:
            claim = await client.claim("worker")
            assert claim is not None
            assert 0 < claim.lease_for.total_seconds() < 30
        finally:
            await client.close()

    asyncio.run(scenario())


def test_startup_retries_api_and_journal_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polycolab.agents.runtime import client as client_module
    from polycolab.execution import service

    adapter = runtime(tmp_path)
    adapter.terminated = [{"run_id": "old", "generation": 1, "worker_id": "old-worker"}]
    monkeypatch.setattr(adapter, "check_ready", AsyncMock())
    monkeypatch.setattr(adapter, "reconcile", AsyncMock())
    acknowledgements = 0

    def acknowledge(*_: object) -> None:
        nonlocal acknowledgements
        acknowledgements += 1
        if acknowledgements == 1:
            raise OSError("synthetic journal storage failure")

    monkeypatch.setattr(adapter, "acknowledge", acknowledge)
    gateway = AsyncMock()
    gateway.incarnation = "new-controller"
    gateway.post.side_effect = [RuntimeGatewayError("runtime_api_failed"), None, None, None]
    monkeypatch.setattr(service, "make_runtime", lambda _: adapter)
    monkeypatch.setattr(service, "read_credential", lambda _: "synthetic")
    monkeypatch.setattr(client_module, "RuntimeClient", lambda *_: gateway)
    original_wait = asyncio.wait_for

    async def short_wait(awaitable: Any, timeout: float) -> Any:
        return await original_wait(awaitable, timeout=min(timeout, 0.001))

    monkeypatch.setattr(asyncio, "wait_for", short_wait)

    async def stop_pool(_: Any, stop: asyncio.Event, *args: object) -> None:
        stop.set()

    monkeypatch.setattr(service, "serve_pool", stop_pool)
    asyncio.run(
        service.run(
            ServiceConfig(
                api_url="http://localhost",
                credential_file="unused",
                state_dir=str(tmp_path),
                images=tuple(adapter.images.values()),
            )
        )
    )
    assert acknowledgements == 2
    assert gateway.post.await_count == 4
    gateway.close.assert_awaited_once()


@pytest.mark.parametrize("body", [b'{"run_id":"\\ud800"}', b"[" * 2000])
def test_invalid_api_json_stays_within_transport_error(body: bytes) -> None:
    async def scenario() -> None:
        client = RuntimeClient(
            "http://localhost",
            "private",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body)),
        )
        try:
            with pytest.raises(RuntimeGatewayError, match="runtime_api_invalid"):
                await client.claim("worker")
        finally:
            await client.close()

    asyncio.run(scenario())


def test_claim_rejects_malformed_tool_definitions() -> None:
    from pydantic import ValidationError

    from polycolab.agents.runtime.client import ClaimEnvelope

    with pytest.raises(ValidationError) as caught:
        ClaimEnvelope.model_validate({"tools": [{"function": {}}]})
    assert any(error["loc"] == ("tools",) for error in caught.value.errors())


def test_preflight_rejects_shared_slot_filesystem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import platform

    adapter = runtime(tmp_path)
    adapter.initialize_slots(2)
    for index in range(2):
        (tmp_path / "slots" / str(index)).mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(os.path, "ismount", lambda _: True)
    monkeypatch.setattr(os, "statvfs", lambda _: SimpleNamespace(f_blocks=1024, f_frsize=4096))
    monkeypatch.setattr(
        adapter,
        "host",
        AsyncMock(
            return_value=json.dumps(
                {
                    "runsc_version": adapter.version,
                    "docker_socket": adapter.socket,
                    "runtime_name": adapter.runtime_name,
                }
            ).encode()
        ),
    )
    with pytest.raises(SandboxUnavailable, match="distinct_slot_filesystems_required"):
        asyncio.run(adapter.check_ready())

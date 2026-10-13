"""Opt-in checks against an idle, isolated Docker/gVisor host configuration.

Only synthetic data is used. Never point this at an active executor state directory.
"""

from __future__ import annotations

import asyncio
import os
import time
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from polycolab.execution.docker import DockerProcess, DockerRuntime
from polycolab.execution.runtime import GuestChannel
from polycolab.execution.service import ServiceConfig, exclusive_controller_state, make_runtime
from polycolab.verification.contracts import ResourceLimits


def configuration() -> ServiceConfig:
    path = os.environ.get("POLYCOLAB_GVISOR_TEST_CONFIG")
    if not path:
        pytest.skip("requires an idle disposable Linux gVisor executor")
    with Path(path).open("rb") as stream:
        config = ServiceConfig.model_validate(tomllib.load(stream))
    assert config.backend == "gvisor"
    return config


def limits(wall: int = 60) -> ResourceLimits:
    return ResourceLimits(
        cpu_count=1,
        cpu_seconds=wall,
        wall_seconds=wall,
        memory_bytes=1024**3,
        process_count=64,
        disk_bytes=4 * 1024**3,
        output_bytes=1024**2,
        log_bytes=1024**2,
        output_files=16,
    )


async def no_model(_: dict[str, object]) -> bytes:
    raise AssertionError("initialization must not call a provider")


async def initialize(channel: GuestChannel) -> None:
    await channel.send(
        {
            "id": 1,
            "method": "initialize",
            "params": {
                "clientInfo": {"name": "polycolab-native", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        }
    )
    async with asyncio.timeout(20):
        reply = await channel.receive()
    assert reply.get("id") == 1 and "result" in reply, reply
    await channel.send({"method": "initialized"})


def test_real_codex_offline_files_and_cleanup() -> None:
    config = configuration()

    async def scenario() -> None:
        adapter = make_runtime(config)
        assert isinstance(adapter, DockerRuntime)
        await adapter.reconcile()
        assert not adapter.terminated
        identity = str(uuid4())
        started = time.monotonic()
        async with adapter.reserve():
            async with adapter.agent(
                name="native-test",
                image=next(iter(adapter.images.values())),
                limits=limits(),
                deadline=datetime.now(UTC) + timedelta(seconds=60),
                inputs={"fixture": b"read only"},
                run_id=identity,
                generation=1,
                worker_id="native-test",
            ) as (process, output):
                assert isinstance(process, DockerProcess)
                channel = GuestChannel(process, no_model, 0)
                await initialize(channel)
                print(f"codex_ready_seconds={time.monotonic() - started:.3f}")
                # The real app-server executes a command inside the existing sandbox.
                code = (
                    "import os,socket; from pathlib import Path; "
                    "assert os.getuid()!=0; "
                    "assert Path('/inputs/fixture').read_text()=='read only'; "
                    "assert not Path('/var/run/docker.sock').exists(); "
                    "assert not Path('/etc/polycolab-execution').exists(); "
                    "assert not os.access('/inputs/fixture',os.W_OK); "
                    "assert not os.access('/opt/polycolab/guest_bridge.py',os.W_OK); "
                    "Path('/outputs/result.txt').write_text('native result'); "
                    "s=socket.socket(); s.settimeout(1); "
                    "assert s.connect_ex(('1.1.1.1',443)) != 0"
                )
                await channel.send(
                    {
                        "id": 2,
                        "method": "command/exec",
                        "params": {
                            "command": ["python3", "-c", code],
                            "cwd": "/workspace",
                            "sandboxPolicy": {"type": "dangerFullAccess"},
                            "timeoutMs": 10000,
                        },
                    }
                )
                async with asyncio.timeout(15):
                    while True:
                        reply = await channel.receive()
                        if reply.get("id") == 2:
                            break
                assert "result" in reply, reply
                assert reply["result"]["exitCode"] == 0, reply  # type: ignore[index]
                await adapter.stop_agent(process)
                assert (output / "result.txt").read_text() == "native result"
        adapter.acknowledge(identity, 1)
        assert adapter.states[0] == "AVAILABLE"
        assert not list((Path(config.state_dir) / "slots").glob("*/work"))

    with exclusive_controller_state(Path(config.state_dir)):
        asyncio.run(scenario())


@pytest.mark.parametrize("journal_fault", [None, "truncated", "missing"])
def test_independent_deadline_guard(journal_fault: str | None) -> None:
    config = configuration()

    async def scenario() -> None:
        adapter = make_runtime(config)
        assert isinstance(adapter, DockerRuntime)
        await adapter.reconcile()
        assert not adapter.terminated
        identity = str(uuid4())
        async with adapter.reserve():
            async with adapter.agent(
                name="deadline-test",
                image=next(iter(adapter.images.values())),
                limits=limits(10),
                deadline=datetime.now(UTC) + timedelta(seconds=10),
                inputs={},
                run_id=identity,
                generation=1,
                worker_id="native-test",
            ) as (process, _):
                assert isinstance(process, DockerProcess)
                journal = adapter.record(process.attempt)
                original = journal.read_bytes()
                try:
                    if journal_fault == "truncated":
                        journal.write_text('{"backend":')
                    elif journal_fault == "missing":
                        journal.unlink()
                    # Keep stdin open and invoke no stop/recovery: only the guard
                    # enforces the deadline after the guest has passed its boot barrier.
                    async with asyncio.timeout(20):
                        await process.wait()
                    info = await adapter.inspect_owned(process.attempt)
                    assert info is not None and not info["State"]["Running"]  # type: ignore[index]
                    group = Path("/sys/fs/cgroup/polycolabexec.slice") / (
                        f"polycolabexec-{process.attempt}.slice"
                    )
                    events = group / "cgroup.events"
                    assert not events.exists() or "populated 1" not in events.read_text()
                finally:
                    # Restore synthetic bookkeeping only after the observation, so
                    # normal teardown can clean up even when the assertion fails.
                    if journal_fault is not None:
                        journal.write_bytes(original)
                        journal.chmod(0o600)
        adapter.acknowledge(identity, 1)

    with exclusive_controller_state(Path(config.state_dir)):
        asyncio.run(scenario())


def test_cancellation_does_not_stop_other_slot() -> None:
    config = configuration()
    if config.capacity < 2:
        pytest.skip("requires two finite slots")

    async def scenario() -> None:
        adapter = make_runtime(config)
        assert isinstance(adapter, DockerRuntime)
        await adapter.reconcile()
        assert not adapter.terminated
        ready = [asyncio.Event(), asyncio.Event()]
        continue_second = asyncio.Event()
        identities = [str(uuid4()), str(uuid4())]

        async def attempt(index: int) -> None:
            async with adapter.reserve():
                async with adapter.agent(
                    name="parallel-test",
                    image=next(iter(adapter.images.values())),
                    limits=limits(),
                    deadline=datetime.now(UTC) + timedelta(seconds=60),
                    inputs={"fixture": str(index).encode()},
                    run_id=identities[index],
                    generation=1,
                    worker_id="native-test",
                ) as (process, _):
                    ready[index].set()
                    if index == 0:
                        await asyncio.Event().wait()
                    else:
                        await continue_second.wait()
                        await initialize(GuestChannel(process, no_model, 0))

        tasks = [asyncio.create_task(attempt(index)) for index in range(2)]
        try:
            async with asyncio.timeout(30):
                await asyncio.gather(*(event.wait() for event in ready))
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            continue_second.set()
            await tasks[1]
            assert set(adapter.states.values()) == {"AVAILABLE"}
            for identity in identities:
                adapter.acknowledge(identity, 1)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    with exclusive_controller_state(Path(config.state_dir)):
        asyncio.run(scenario())


def test_controller_sigkill_termination_and_restart_reconciliation(tmp_path: Path) -> None:
    import subprocess
    import sys

    config = configuration()
    identity = str(uuid4())
    ready = tmp_path / "ready"
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__)), identity, str(ready)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        until = time.monotonic() + 20
        while not ready.exists():
            assert child.poll() is None, "synthetic controller failed before guest startup"
            assert time.monotonic() < until, "synthetic controller startup timed out"
            time.sleep(0.05)
        attempt = ready.read_text()
        child.kill()
        child.wait(timeout=5)

        async def recover() -> None:
            adapter = make_runtime(config)
            assert isinstance(adapter, DockerRuntime)
            # Observe termination before invoking any recovery/stop operation.
            async with asyncio.timeout(25):
                while True:
                    info = await adapter.inspect_owned(attempt)
                    assert info is not None
                    if not info["State"]["Running"]:  # type: ignore[index]
                        break
                    await asyncio.sleep(0.1)
            with exclusive_controller_state(Path(config.state_dir)):
                await adapter.reconcile()
                assert any(row["run_id"] == identity for row in adapter.terminated)
                adapter.acknowledge(identity, 1)
                assert set(adapter.states.values()) == {"AVAILABLE"}
                assert not list((Path(config.state_dir) / "slots").glob("*/work"))

        asyncio.run(recover())
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


async def crash_child(identity: str, ready: Path) -> None:
    config = configuration()
    adapter = make_runtime(config)
    assert isinstance(adapter, DockerRuntime)
    with exclusive_controller_state(Path(config.state_dir)):
        await adapter.reconcile()
        assert not adapter.terminated
        async with adapter.reserve():
            async with adapter.agent(
                name="crash-test",
                image=next(iter(adapter.images.values())),
                limits=limits(15),
                deadline=datetime.now(UTC) + timedelta(seconds=15),
                inputs={},
                run_id=identity,
                generation=1,
                worker_id="native-test",
            ) as (process, _):
                assert isinstance(process, DockerProcess)
                ready.write_text(process.attempt)
                await asyncio.Event().wait()


if __name__ == "__main__":
    import sys

    asyncio.run(crash_child(sys.argv[1], Path(sys.argv[2])))

"""Opt-in native VM/Codex isolation smoke test on a disposable execution account.

POLYCOLAB_NATIVE_CONTROLLER_CONFIG must reference prepared, private slot mounts.
No provider credential or application API is used. This is not provider/browser
or resource-exhaustion acceptance.
"""

import asyncio
import os
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from polycolab.execution.linux import LinuxRuntime
from polycolab.execution.microsandbox import GuestChannel
from polycolab.execution.service import ServiceConfig, exclusive_controller_state
from polycolab.verification.contracts import ResourceLimits


def test_cancelling_one_native_vm_preserves_another() -> None:
    path = os.environ.get("POLYCOLAB_NATIVE_CONTROLLER_CONFIG")
    if not path:
        pytest.skip("requires a prepared disposable Linux execution host")
    with Path(path).open("rb") as stream:
        config = ServiceConfig.model_validate(tomllib.load(stream))
    assert config.capacity >= 2
    images = [image for image in config.images if image.language == "AGENT"]
    assert len(images) == 1

    async def scenario() -> None:
        runtime = LinuxRuntime(Path(config.state_dir), config.images, config.capacity)
        await runtime.reconcile()
        assert not runtime.terminated, (
            "use an idle disposable state with no unacknowledged attempts"
        )
        ready = [asyncio.Event(), asyncio.Event()]
        proceed = asyncio.Event()
        completed: list[int] = []
        run_ids: dict[int, str] = {}

        async def unexpected_model(_: dict[str, object]) -> bytes:
            raise AssertionError("initialization must not dispatch a provider request")

        async def attempt(index: int) -> None:
            run_id = str(uuid4())
            run_ids[index] = run_id
            async with runtime.reserve() as slot:
                assert slot is not None
                async with runtime.agent(
                    name="native-acceptance-" + run_id,
                    image=images[0],
                    limits=ResourceLimits(
                        cpu_count=1,
                        cpu_seconds=120,
                        wall_seconds=120,
                        memory_bytes=1024**3,
                        process_count=64,
                        disk_bytes=4 * 1024**3,
                        log_bytes=1024**2,
                        output_bytes=1024**2,
                        output_files=16,
                    ),
                    deadline=datetime.now(UTC) + timedelta(seconds=120),
                    inputs={},
                    run_id=run_id,
                    generation=1,
                    worker_id="native-acceptance",
                ) as (process, _):
                    ready[index].set()
                    await proceed.wait()
                    channel = GuestChannel(process, unexpected_model, 0)
                    await channel.send(
                        {
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "clientInfo": {"name": "polycolab-acceptance", "version": "1"},
                                "capabilities": {"experimentalApi": True},
                            },
                        }
                    )
                    async with asyncio.timeout(20):
                        reply = await channel.receive()
                    assert reply.get("id") == 1 and "result" in reply
                    completed.append(index)
            runtime.acknowledge(run_id, 1)

        tasks = [asyncio.create_task(attempt(index)) for index in range(2)]
        try:
            async with asyncio.timeout(60):
                await asyncio.gather(*(event.wait() for event in ready))
            tasks[0].cancel()
            result = (await asyncio.gather(tasks[0], return_exceptions=True))[0]
            assert isinstance(result, asyncio.CancelledError)
            runtime.acknowledge(run_ids[0], 1)
            proceed.set()
            await tasks[1]
            assert completed == [1]
            assert all(state == "AVAILABLE" for state in runtime.states.values())
            assert not any((Path(config.state_dir) / "slots").glob("*/work"))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    with exclusive_controller_state(Path(config.state_dir)):
        asyncio.run(scenario())

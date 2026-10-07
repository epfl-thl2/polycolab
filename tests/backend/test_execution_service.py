"""Host lifecycle tests; no SBX or Linux isolation evidence."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from polycolab.execution.controller import ExecutionController
from polycolab.execution.microsandbox import MicrosandboxRuntime
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.execution.service import ServiceConfig, read_credential, run, serve


def test_credential_private_file(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("test-secret\n")
    path.chmod(0o600)
    assert read_credential(path) == "test-secret"
    path.chmod(0o644)
    with pytest.raises(ValueError):
        read_credential(path)


def test_credential_rejects_link(tmp_path: Path) -> None:
    path = tmp_path / "token"
    path.write_text("secret")
    path.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(path)
    with pytest.raises(OSError):
        read_credential(link)


@pytest.mark.parametrize("value", ["", "a" * 258, "secret\nextra", "secret ", "é"])
def test_credential_rejects_invalid(tmp_path: Path, value: str) -> None:
    path = tmp_path / "token"
    path.write_text(value)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        read_credential(path)


def test_gate_precedes_credentials_and_api() -> None:
    with pytest.raises(SandboxUnavailable, match="linux_x86_64_required|runtime_image_unavailable"):
        asyncio.run(run(ServiceConfig(api_url="http://localhost", credential_file="/missing")))


def test_gate_precedes_claim() -> None:
    gateway = AsyncMock()
    controller = ExecutionController(gateway, MicrosandboxRuntime(Path("/unavailable")))
    with pytest.raises(SandboxUnavailable):
        asyncio.run(serve(controller, asyncio.Event(), 0.01))
    gateway.claim.assert_not_called()
    gateway.close.assert_awaited_once()


def test_stop_awaits_cleanup_before_gateway_close() -> None:
    async def scenario() -> None:
        started = asyncio.Event()
        stop = asyncio.Event()
        events: list[str] = []

        async def work() -> bool:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                events.append("cleanup")
            return True

        controller = AsyncMock()
        controller.once.side_effect = work
        controller.gateway.close.side_effect = lambda: events.append("closed")
        service = asyncio.create_task(serve(controller, stop, 0.01))
        await started.wait()
        stop.set()
        await service
        assert events == ["cleanup", "closed"]
        controller.once.assert_awaited_once()

    asyncio.run(scenario())


def test_idle_poll_can_stop_without_second_claim() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        controller = AsyncMock()

        async def idle() -> bool:
            stop.set()
            return False

        controller.once.side_effect = idle
        await serve(controller, stop, 60)
        controller.once.assert_awaited_once()
        controller.gateway.close.assert_awaited_once()

    asyncio.run(scenario())


def test_shutdown_reports_uncertain_cleanup_and_closes_gateway() -> None:
    async def scenario() -> None:
        started, stop = asyncio.Event(), asyncio.Event()
        controller = AsyncMock()

        async def work() -> bool:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise SandboxUnavailable("sandbox_cleanup_unconfirmed") from None
            return True

        controller.once.side_effect = work
        service = asyncio.create_task(serve(controller, stop, 0.01))
        await started.wait()
        stop.set()
        with pytest.raises(SandboxUnavailable, match="cleanup_unconfirmed"):
            await service
        controller.once.assert_awaited_once()
        controller.gateway.close.assert_awaited_once()

    asyncio.run(scenario())


def test_pool_cancels_every_attempt_before_closing_shared_transport() -> None:
    from polycolab.execution.service import serve_pool

    async def scenario() -> None:
        stop, full = asyncio.Event(), asyncio.Event()
        active = 0
        cleaned = 0
        controller = AsyncMock()

        async def work() -> bool:
            nonlocal active, cleaned
            active += 1
            if active == 4:
                full.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned += 1
            return True

        controller.once.side_effect = work
        task = asyncio.create_task(serve_pool(controller, stop, 0.01, 4))
        await asyncio.wait_for(full.wait(), 1)
        stop.set()
        await task
        assert cleaned == 4
        controller.gateway.close.assert_awaited_once()

    asyncio.run(scenario())

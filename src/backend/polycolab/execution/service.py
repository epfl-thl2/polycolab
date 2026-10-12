"""Host controller lifecycle. Microsandbox deployment acceptance remains gated."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import signal
import stat
import sys
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from polycolab.execution.linux import LinuxRuntime
from polycolab.execution.microsandbox import ImagePolicy
from polycolab.execution.sandbox import SandboxUnavailable


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    api_url: str
    credential_file: str | None = None
    agent_credential_file: str | None = None
    worker_id: str = Field(default="codex-controller", min_length=1, max_length=200)
    state_dir: str = "/var/lib/polycolab-execution"
    images: tuple[ImagePolicy, ...] = ()
    capacity: int = Field(default=4, ge=1, le=64)
    poll_seconds: float = Field(default=5.0, ge=0.1, le=60)

    @field_validator("images", mode="before")
    @classmethod
    def image_policies(cls, value: object) -> object:
        if isinstance(value, (tuple, list)):
            return tuple(TypeAdapter(ImagePolicy).validate_python(item) for item in value)
        return value


def read_credential(path: Path) -> str:
    """Read only a private, owned regular file; never print its contents."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > 257
        ):
            raise ValueError("invalid credential file")
        token = os.read(fd, 258).decode("ascii").removesuffix("\n")
        if not token or len(token) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("invalid credential file")
        return token
    finally:
        os.close(fd)


@contextmanager
def exclusive_controller_state(path: Path) -> Iterator[None]:
    """One controller may reconcile/execute in this private host namespace."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError("controller state must be private and owned")
        lock = os.open("controller.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
            raise ValueError("invalid controller lock")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        if lock is not None:
            os.close(lock)
        os.close(fd)


class Closable(Protocol):
    async def close(self) -> None: ...


class Controller(Protocol):
    @property
    def gateway(self) -> Closable: ...

    async def once(self) -> bool: ...


async def serve(
    controller: Controller, stop: asyncio.Event, poll_seconds: float, *, close_gateway: bool = True
) -> None:
    """Serial claims; signals cancel and await runtime cleanup before closing HTTP.

    The controller contains run-local failures and quarantines uncertain slots.
    Unhandled host-wide authority or containment failures stop the pool.
    """
    stopping = asyncio.create_task(stop.wait())
    attempt: asyncio.Task[bool] | None = None
    try:
        while not stop.is_set():
            attempt = asyncio.create_task(controller.once())
            done, _ = await asyncio.wait((attempt, stopping), return_when=asyncio.FIRST_COMPLETED)
            if stopping in done:
                break
            worked = await attempt
            if not worked:
                try:
                    await asyncio.wait_for(asyncio.shield(stopping), timeout=poll_seconds)
                except TimeoutError:
                    pass
    finally:
        failure = None
        if attempt is not None:
            attempt.cancel()
            results = await asyncio.gather(attempt, return_exceptions=True)
            if isinstance(results[0], SandboxUnavailable):
                failure = results[0]
        stopping.cancel()
        await asyncio.gather(stopping, return_exceptions=True)
        if close_gateway:
            await controller.gateway.close()
        if failure is not None:
            raise failure


async def serve_pool(
    controller: Controller, stop: asyncio.Event, poll_seconds: float, capacity: int
) -> None:
    if not 1 <= capacity <= 64:
        raise ValueError("invalid controller capacity")
    try:
        async with asyncio.TaskGroup() as group:
            for _ in range(capacity):
                group.create_task(serve(controller, stop, poll_seconds, close_gateway=False))
    finally:
        await controller.gateway.close()


async def run(config: ServiceConfig) -> None:
    from polycolab.agents.runtime.client import RuntimeClient
    from polycolab.agents.runtime.controller import AgentController

    runtime = LinuxRuntime(Path(config.state_dir), config.images, config.capacity)
    await runtime.check_ready()
    with exclusive_controller_state(Path(config.state_dir)):
        await runtime.reconcile()
        credential = config.agent_credential_file or config.credential_file
        if credential is None:
            raise ValueError("agent credential file required")
        gateway = RuntimeClient(config.api_url, read_credential(Path(credential)))
        for old in runtime.terminated:
            await gateway.post(
                f"/internal/v1/runtime/runs/{old['run_id']}/terminated",
                {"worker_id": old["worker_id"], "lease_generation": old["generation"]},
            )
            runtime.acknowledge(str(old["run_id"]), int(str(old["generation"])))
        controller = AgentController(gateway, runtime, config.worker_id)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
        try:
            agent_images = [image for image in config.images if image.language == "AGENT"]
            if len(agent_images) != 1:
                raise ValueError("exactly one agent image required")

            async def advertise() -> None:
                await gateway.post(
                    "/internal/v1/runtime/executors/readiness",
                    {
                        "worker_id": config.worker_id,
                        "engine": "codex",
                        "image_digest": agent_images[0].reference.rsplit("@sha256:", 1)[-1],
                        "capacity": sum(
                            state != "QUARANTINED" for state in runtime.states.values()
                        ),
                        "slot_states": runtime.states,
                        "incarnation": gateway.incarnation,
                        "protocol_version": 4,
                    },
                )

            from polycolab.agents.runtime.remote import RuntimeGatewayError

            while not stop.is_set():
                try:
                    await advertise()
                    break
                except RuntimeGatewayError as exc:
                    if exc.code not in {"runtime_api_unavailable", "executor_incarnation_conflict"}:
                        raise
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=5)
                    except TimeoutError:
                        pass

            async def readiness() -> None:
                while not stop.is_set():
                    try:
                        await asyncio.wait_for(stop.wait(), timeout=10)
                    except TimeoutError:
                        try:
                            await advertise()
                        except RuntimeGatewayError as exc:
                            if exc.code not in {"runtime_api_unavailable", "runtime_api_failed"}:
                                raise

            async with asyncio.TaskGroup() as group:
                group.create_task(readiness())
                group.create_task(
                    serve_pool(controller, stop, config.poll_seconds, config.capacity)
                )
        finally:
            for signum in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        with args.config.open("rb") as stream:
            config = ServiceConfig.model_validate(tomllib.load(stream))
        asyncio.run(run(config))
    except SandboxUnavailable:
        print("execution unavailable: runtime acceptance or cleanup failed", file=sys.stderr)
        return 78
    except OSError, ValueError, ValidationError:
        print("execution configuration invalid", file=sys.stderr)
        return 78
    except Exception:
        # Exceptions can contain transport or subprocess credentials/source.
        print("execution service stopped; operator investigation required", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

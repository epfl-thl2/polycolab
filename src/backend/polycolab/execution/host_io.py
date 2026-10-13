"""Bounded host subprocesses and cancellation-safe filesystem work."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path

from polycolab.execution.sandbox import SandboxUnavailable


async def blocking[T](function: Callable[..., T], *args: object, **kwargs: object) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


def atomic_record(path: Path, value: dict[str, object]) -> None:
    encoded = json.dumps(value, separators=(",", ":")).encode()
    if len(encoded) > 16384:
        raise SandboxUnavailable("attempt_journal_limit")
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("attempt journal write failed")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class PipeProcess:
    def __init__(self, process: asyncio.subprocess.Process, log_bytes: int) -> None:
        self.process, self.remaining = process, log_bytes
        self.unit: str | None = None

    async def send(self, data: bytes) -> None:
        if self.process.stdin is None:
            raise SandboxUnavailable("executor_stdin_closed")
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def receive(self) -> bytes | None:
        assert self.process.stdout is not None
        try:
            data = await self.process.stdout.readline()
        except ValueError:
            raise SandboxUnavailable("executor_frame_limit") from None
        if not data:
            return None
        self.remaining -= len(data)
        if self.remaining < 0:
            raise SandboxUnavailable("executor_log_limit")
        return data.rstrip(b"\n")

    async def wait(self) -> int:
        return await self.process.wait()


async def command(
    *args: str, timeout: float = 15, allow_missing: bool = False, env: dict[str, str] | None = None
) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=65_536,
        env=env,
    )
    try:
        async with asyncio.timeout(timeout):
            assert process.stdout is not None
            data = bytearray()
            while chunk := await process.stdout.read(4096):
                if len(data) + len(chunk) > 65536:
                    raise SandboxUnavailable("host_command_output_limit")
                data.extend(chunk)
            await process.wait()
            stdout = bytes(data)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if len(stdout) > 65_536 or (process.returncode != 0 and not allow_missing):
        raise SandboxUnavailable("host_command_failed")
    return stdout

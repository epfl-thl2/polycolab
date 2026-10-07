"""Linux/systemd containment for microsandbox attempts.

A pre-provisioned, size-bounded filesystem per slot contains *all* mutable SDK
state, guest disks, inputs, outputs and logs. Each VM belongs to a transient user
service whose wall deadline and cgroup survive controller death.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import stat
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from polycolab.execution.microsandbox import (
    MICROSANDBOX_VERSION,
    ImagePolicy,
    MicrosandboxRuntime,
    Process,
)
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.verification.contracts import ResourceLimits, validate_path


def isolated_executor() -> None:
    """Check actual containment; no environment flag can enable bare execution."""
    if platform.system() != "Linux" or version("microsandbox") != MICROSANDBOX_VERSION:
        raise SandboxUnavailable("linux_microsandbox_required")
    cgroup = Path("/proc/self/cgroup").read_text().strip().split("0::")[-1]
    if "/polycolab-attempt-" not in cgroup or ".." in cgroup:
        raise SandboxUnavailable("executor_service_required")
    root = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
    for name in ("memory.max", "pids.max"):
        value = (root / name).read_text().strip()
        if not value.isdecimal() or int(value) <= 0:
            raise SandboxUnavailable("executor_cgroup_unbounded")
    if (root / "cpu.max").read_text().split()[0] == "max":
        raise SandboxUnavailable("executor_cpu_unbounded")


class SlotQuarantined(SandboxUnavailable):
    pass


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


class LinuxRuntime(MicrosandboxRuntime):
    def __init__(self, state_dir: Path, images: tuple[ImagePolicy, ...], capacity: int) -> None:
        super().__init__(state_dir, images)
        self.capacity = capacity
        self.images_checked = False
        self.slots: asyncio.Queue[Path] = asyncio.Queue()
        for ordinal in range(capacity):
            self.slots.put_nowait(state_dir / "slots" / str(ordinal))
        self.terminated: list[dict[str, object]] = []
        self.states = {ordinal: "AVAILABLE" for ordinal in range(capacity)}
        self.reserved: ContextVar[Path | None] = ContextVar("hosted_slot", default=None)

    @asynccontextmanager
    async def reserve(self) -> AsyncIterator[int | None]:
        try:
            slot = self.slots.get_nowait()
            while self.states[int(slot.name)] == "QUARANTINED":
                slot = self.slots.get_nowait()
        except asyncio.QueueEmpty:
            yield None
            return
        ordinal = int(slot.name)
        self.states[ordinal] = "BUSY"
        token = self.reserved.set(slot)
        try:
            yield ordinal
        finally:
            self.reserved.reset(token)
            if self.states[ordinal] != "QUARANTINED":
                self.states[ordinal] = "AVAILABLE"
                self.slots.put_nowait(slot)

    async def check_ready(self) -> None:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise SandboxUnavailable("linux_x86_64_required")
        if version("microsandbox") != MICROSANDBOX_VERSION or not self.images:
            raise SandboxUnavailable("runtime_image_unavailable")
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            raise SandboxUnavailable("kvm_unavailable")
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise SandboxUnavailable("cgroup_v2_required")
        for ordinal in range(self.capacity):
            slot = self.state_dir / "slots" / str(ordinal)
            info = slot.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or not os.path.ismount(slot)
            ):
                raise SandboxUnavailable("private_slot_mount_required")
            # A real finite filesystem, not an ordinary directory on the host root.
            if os.statvfs(slot).f_blocks * os.statvfs(slot).f_frsize > 4 * 1024**3:
                raise SandboxUnavailable("slot_disk_limit_invalid")
        await command("systemctl", "--user", "show-environment")
        if not self.images_checked:
            for ordinal in range(self.capacity):
                slot = self.state_dir / "slots" / str(ordinal)
                try:
                    for image in self.images.values():
                        await command(
                            sys.executable,
                            "-m",
                            "polycolab.execution.preflight",
                            "--image",
                            image.reference,
                            timeout=30,
                            env={
                                "PATH": os.defpath,
                                "MSB_HOME": str(slot / "msb"),
                                "HOME": str(slot),
                            },
                        )
                except SandboxUnavailable:
                    self.states[ordinal] = "QUARANTINED"
            self.images_checked = True

    async def _stop(self, unit: str) -> None:
        await command("systemctl", "--user", "stop", unit, allow_missing=True)
        state = (
            await command(
                "systemctl",
                "--user",
                "show",
                unit,
                "--property=ActiveState",
                "--value",
                allow_missing=True,
            )
        ).strip()
        if state not in {b"inactive", b"failed"}:
            raise SandboxUnavailable("sandbox_cleanup_unconfirmed")
        group = (
            (
                await command(
                    "systemctl",
                    "--user",
                    "show",
                    unit,
                    "--property=ControlGroup",
                    "--value",
                    allow_missing=True,
                )
            )
            .decode()
            .strip()
        )
        if group:
            if not group.startswith("/") or ".." in group:
                raise SandboxUnavailable("invalid_executor_cgroup")
            events = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events"
            if events.exists() and "populated 1" in events.read_text():
                raise SandboxUnavailable("sandbox_cleanup_unconfirmed")
        # --wait's process is also awaited by the live caller. systemd stop with
        # KillMode=control-group waits for every descendant, including the VM.

    async def reconcile(self) -> None:
        await self.check_ready()
        self.terminated = []
        for record in sorted((self.state_dir / "attempts").glob("*.json")):
            value = json.loads(record.read_text())
            unit = value["unit"]
            if not isinstance(unit, str) or unit != f"polycolab-attempt-{record.stem}.service":
                raise SandboxUnavailable("invalid_attempt_journal")
            ordinal = int(str(value["slot"]).rsplit("/", 1)[-1])
            if not 0 <= ordinal < self.capacity or value["slot"] != str(
                self.state_dir / "slots" / str(ordinal)
            ):
                raise SandboxUnavailable("invalid_attempt_journal")
            try:
                await self._stop(unit)
                work = self.state_dir / "slots" / str(ordinal) / "work"
                if work.exists():
                    shutil.rmtree(work)
                self.terminated.append(value)
            except SandboxUnavailable, OSError:
                self.states[ordinal] = "QUARANTINED"
        self.slots = asyncio.Queue()
        for ordinal, state in self.states.items():
            if state != "QUARANTINED":
                self.slots.put_nowait(self.state_dir / "slots" / str(ordinal))
        # The service reports the exact old generation before deleting journals.

    @asynccontextmanager
    async def agent(
        self,
        *,
        name: str,
        image: ImagePolicy,
        limits: ResourceLimits,
        deadline: datetime,
        inputs: dict[str, bytes],
        run_id: str,
        generation: int,
        worker_id: str,
    ) -> AsyncIterator[tuple[Process, Path]]:
        reserved = self.reserved.get()
        slot = reserved if reserved is not None else await self.slots.get()
        ordinal = int(slot.name)
        process = None
        unit = "polycolab-attempt-" + uuid4().hex + ".service"
        record = (
            self.state_dir
            / "attempts"
            / (unit.removeprefix("polycolab-attempt-").removesuffix(".service") + ".json")
        )
        stopped = False
        try:
            remaining = min(
                limits.wall_seconds, (deadline.astimezone(UTC) - datetime.now(UTC)).total_seconds()
            )
            disk_size = os.statvfs(slot).f_blocks * os.statvfs(slot).f_frsize
            if remaining <= 0 or disk_size > limits.disk_bytes:
                raise SandboxUnavailable("attempt_resource_mismatch")
            work = slot / "work"
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(mode=0o700)
            source, output = work / "inputs", work / "outputs"
            source.mkdir()
            output.mkdir()
            if sum(map(len, inputs.values())) > 16 * 1024**2:
                raise SandboxUnavailable("sandbox_input_limit_exceeded")
            for path, data in inputs.items():
                validate_path(path)
                target = source / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            config = {
                "name": name,
                "image": image.reference,
                "limits": limits.model_dump(mode="json"),
                "deadline": deadline.isoformat(),
                "work": str(work),
            }
            (work / "attempt.json").write_text(json.dumps(config))
            record.parent.mkdir(mode=0o700, exist_ok=True)
            atomic_record(
                record,
                {
                    "version": 1,
                    "unit": unit,
                    "run_id": run_id,
                    "generation": generation,
                    "worker_id": worker_id,
                    "slot": str(slot),
                },
            )
            # SDK image/cache/runtime writes all remain in this bounded slot.
            cpu_quota = min(limits.cpu_count, limits.cpu_seconds / remaining) * 100
            process = await asyncio.create_subprocess_exec(
                "systemd-run",
                "--user",
                "--quiet",
                "--pipe",
                "--wait",
                "--collect",
                "--unit=" + unit,
                "--property=KillMode=control-group",
                "--property=TimeoutStopSec=5",
                f"--property=RuntimeMaxSec={remaining:.3f}",
                f"--property=MemoryMax={limits.memory_bytes + 512 * 1024**2}",
                f"--property=CPUQuota={cpu_quota:.3f}%",
                "--property=TasksMax=256",
                "--property=NoNewPrivileges=yes",
                "--property=ProtectSystem=strict",
                "--property=ProtectHome=yes",
                "--property=InaccessiblePaths=/etc/polycolab-execution",
                "--property=PrivateTmp=yes",
                "--property=ReadWritePaths=" + str(slot),
                "--setenv=MSB_HOME=" + str(slot / "msb"),
                "--setenv=HOME=" + str(work),
                "--setenv=PYTHONUNBUFFERED=1",
                sys.executable,
                "-m",
                "polycolab.execution.executor",
                str(work / "attempt.json"),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=2_000_000,
            )
            channel = PipeProcess(process, 32 * 1024**2)
            channel.unit = unit
            async with asyncio.timeout(min(30, remaining)):
                if await channel.receive() != b'{"kind":"ready"}':
                    raise SandboxUnavailable("executor_start_failed")
            yield channel, output
        finally:

            async def cleanup() -> None:
                nonlocal stopped
                if process is not None and process.stdin is not None:
                    process.stdin.close()
                    try:
                        async with asyncio.timeout(8):
                            await process.wait()
                    except TimeoutError:
                        pass
                await self._stop(unit)
                if process is not None:
                    async with asyncio.timeout(5):
                        await process.wait()
                work = slot / "work"
                if work.exists():
                    shutil.rmtree(work)
                stopped = True

            async def guarded_cleanup() -> None:
                try:
                    await cleanup()
                except Exception:
                    self.states[ordinal] = "QUARANTINED"
                    try:
                        atomic_record(
                            record,
                            {
                                "version": 1,
                                "unit": unit,
                                "run_id": run_id,
                                "generation": generation,
                                "worker_id": worker_id,
                                "slot": str(slot),
                                "quarantined": True,
                            },
                        )
                    finally:
                        # A full journal filesystem must never turn an unconfirmed stop
                        # into a positive termination acknowledgement.
                        raise SlotQuarantined("sandbox_cleanup_unconfirmed") from None

            task = asyncio.create_task(guarded_cleanup())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
            finally:
                if stopped and reserved is None:
                    self.slots.put_nowait(slot)
            # The caller collects declared files before leaving the context.

    async def stop_agent(self, process: Process) -> None:
        if not isinstance(process, PipeProcess) or process.unit is None:
            raise SandboxUnavailable("invalid_executor_process")
        if process.process.stdin is not None:
            process.process.stdin.close()
        try:
            async with asyncio.timeout(8):
                await process.wait()
        except TimeoutError:
            pass
        await self._stop(process.unit)
        async with asyncio.timeout(5):
            await process.wait()

    def acknowledge(self, run_id: str, generation: int) -> None:
        for record in (self.state_dir / "attempts").glob("*.json"):
            data = json.loads(record.read_text())
            if data["run_id"] == run_id and data["generation"] == generation:
                record.unlink()

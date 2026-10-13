"""Offline Docker/runsc adapter with independently enforced host deadlines."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from polycolab.execution.host_io import PipeProcess, atomic_record, blocking, command
from polycolab.execution.runtime import ImagePolicy, Process, SlotQuarantined
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.execution.slots import SlotPool
from polycolab.verification.contracts import ResourceLimits, validate_path


class DockerProcess(PipeProcess):
    def __init__(self, process: asyncio.subprocess.Process, attempt: str) -> None:
        super().__init__(process, 32 * 1024**2)
        self.attempt = attempt


class DockerRuntime(SlotPool):
    backend = "gvisor"

    def __init__(
        self,
        state_dir: Path,
        images: tuple[ImagePolicy, ...],
        capacity: int,
        *,
        version: str,
        socket: str,
        helper: str,
        runtime_name: str,
    ) -> None:
        self.state_dir = state_dir
        self.owner = hashlib.sha256(str(state_dir.resolve()).encode()).hexdigest()
        self.images = {item.reference.rsplit("@sha256:", 1)[1]: item for item in images}
        self.version, self.socket, self.helper, self.runtime_name = (
            version,
            socket,
            helper,
            runtime_name,
        )
        self.initialize_slots(capacity)
        self.environment = {"PATH": os.defpath, "HOME": "/nonexistent", "LANG": "C"}

    def docker_args(self, *args: str) -> tuple[str, ...]:
        return ("docker", "--host", "unix://" + self.socket, *args)

    async def docker(self, *args: str) -> bytes:
        return await command(*self.docker_args(*args), env=self.environment)

    async def host(self, action: str, attempt: str | None = None) -> bytes:
        return await command(
            "sudo",
            "-n",
            self.helper,
            action,
            *((attempt,) if attempt else ()),
            timeout=45,
            env=self.environment,
        )

    async def check_ready(self) -> None:
        if platform.system() != "Linux" or platform.machine() != "x86_64" or not self.images:
            raise SandboxUnavailable("linux_runtime_required")
        info = json.loads(await self.host("check"))
        if (info["runsc_version"], info["docker_socket"], info["runtime_name"]) != (
            self.version,
            self.socket,
            self.runtime_name,
        ):
            raise SandboxUnavailable("runtime_identity_mismatch")
        devices: set[int] = set()
        for ordinal in range(self.capacity):
            slot = self.state_dir / "slots" / str(ordinal)
            details = slot.lstat()
            if details.st_dev in devices:
                raise SandboxUnavailable("distinct_slot_filesystems_required")
            devices.add(details.st_dev)
            if (
                not stat.S_ISDIR(details.st_mode)
                or details.st_uid != os.geteuid()
                or details.st_mode & 0o077
                or not os.path.ismount(slot)
                or os.statvfs(slot).f_blocks * os.statvfs(slot).f_frsize > 4 * 1024**3
            ):
                raise SandboxUnavailable("private_bounded_slot_required")
        for image in self.images.values():
            value = json.loads(await self.docker("image", "inspect", image.reference))[0]
            if (
                image.reference not in value.get("RepoDigests", [])
                or value["Architecture"] != "amd64"
                or value["Os"] != "linux"
                or value["Config"].get("Volumes")
            ):
                raise SandboxUnavailable("cached_image_identity_mismatch")

    def record(self, attempt: str) -> Path:
        if len(attempt) != 32 or any(c not in "0123456789abcdef" for c in attempt):
            raise SandboxUnavailable("invalid_attempt_identity")
        return self.state_dir / "attempts" / (attempt + ".json")

    async def inspect_owned(self, attempt: str) -> dict[str, object] | None:
        # Successful list distinguishes absence from a failed Docker API operation.
        name = "polycolab-exec-" + attempt
        ids = (
            await self.docker(
                "ps", "--all", "--filter", "name=^/" + name + "$", "--format", "{{.ID}}"
            )
        ).split()
        if not ids:
            return None
        info = json.loads(await self.docker("inspect", name))[0]
        labels = info["Config"].get("Labels") or {}
        if (
            labels.get("polycolab.executor") != self.owner
            or labels.get("polycolab.attempt") != attempt
        ):
            raise SandboxUnavailable("container_ownership_mismatch")
        return info  # type: ignore[no-any-return]

    async def stop(self, attempt: str) -> None:
        await self.host("stop", attempt)
        info = await self.inspect_owned(attempt)
        if info is not None:
            state = info["State"]
            if not isinstance(state, dict):
                raise SandboxUnavailable("container_state_invalid")
            # Docker can briefly lag behind the kernel's cgroup termination.
            if state.get("Running"):
                await self.docker("kill", "polycolab-exec-" + attempt)
            if state.get("Status") != "created":
                await self.docker("wait", "polycolab-exec-" + attempt)
            info = await self.inspect_owned(attempt)
            if (
                info is not None
                and isinstance(info["State"], dict)
                and info["State"].get("Running")
            ):
                raise SandboxUnavailable("sandbox_cleanup_unconfirmed")

    async def cleanup(self, attempt: str, slot: Path) -> None:
        await self.stop(attempt)
        if await self.inspect_owned(attempt) is not None:
            await self.docker("rm", "polycolab-exec-" + attempt)
        await self.host("release", attempt)
        work = slot / "work"
        if work.exists():
            await blocking(shutil.rmtree, work)

    async def reconcile(self) -> None:
        await self.check_ready()
        self.terminated = []
        journal = self.state_dir / "attempts"
        journal.mkdir(mode=0o700, exist_ok=True)
        records = sorted(journal.glob("*.json"))
        known = {path.stem for path in records}
        live = (
            (
                await self.docker(
                    "ps",
                    "--all",
                    "--filter",
                    "label=polycolab.executor=" + self.owner,
                    "--format",
                    "{{.Names}}",
                )
            )
            .decode()
            .splitlines()
        )
        if any(name.removeprefix("polycolab-exec-") not in known for name in live):
            raise SandboxUnavailable("owned_container_without_journal")
        for path in records:
            row = json.loads(await blocking(path.read_text))
            if (
                row.get("backend") != self.backend
                or row.get("container") != "polycolab-exec-" + path.stem
            ):
                raise SandboxUnavailable("journal_backend_mismatch")
            ordinal = row["slot_id"]
            if type(ordinal) is not int or not 0 <= ordinal < 64:
                raise SandboxUnavailable("invalid_slot_journal")
            slot = self.state_dir / "slots" / str(ordinal)
            try:
                await self.cleanup(path.stem, slot)
                self.terminated.append(row)
            except SandboxUnavailable, OSError:
                if ordinal >= self.capacity:
                    raise SandboxUnavailable("retired_slot_cleanup_unconfirmed") from None
                self.states[ordinal] = "QUARANTINED"
        self.slots = asyncio.Queue()
        for ordinal, state in self.states.items():
            if state != "QUARANTINED":
                self.slots.put_nowait(self.state_dir / "slots" / str(ordinal))

    def prepare_files(self, slot: Path, inputs: dict[str, bytes], limits: ResourceLimits) -> Path:
        if sum(map(len, inputs.values())) > min(limits.disk_bytes, 16 * 1024**2):
            raise SandboxUnavailable("sandbox_input_limit_exceeded")
        if os.statvfs(slot).f_blocks * os.statvfs(slot).f_frsize > limits.disk_bytes:
            raise SandboxUnavailable("attempt_resource_mismatch")
        work = slot / "work"
        if work.exists():
            raise SandboxUnavailable("unclean_slot")
        work.mkdir(mode=0o700)
        for name in ("inputs", "outputs", "workspace", "home", "tmp", "run", "shm"):
            (work / name).mkdir(mode=0o700)
        for path, data in inputs.items():
            validate_path(path)
            destination = work / "inputs" / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        return work

    def create_args(
        self,
        attempt: str,
        work: Path,
        image: ImagePolicy,
        limits: ResourceLimits,
        deadline: datetime,
    ) -> tuple[str, ...]:
        # Run as the dedicated non-root host account so collected files stay owned.
        args = [
            "create",
            "--name",
            "polycolab-exec-" + attempt,
            "--pull=never",
            "--runtime",
            self.runtime_name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--restart=no",
            "--log-driver=none",
            "--ipc=none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--cgroup-parent=polycolabexec-" + attempt + ".slice",
            "--memory",
            str(limits.memory_bytes),
            "--memory-swap",
            str(limits.memory_bytes),
            "--cpus",
            str(limits.cpu_count),
            "--pids-limit=256",
            "--ulimit",
            f"nproc={limits.process_count}:{limits.process_count}",
            "--label",
            "polycolab.executor=" + self.owner,
            "--label",
            "polycolab.attempt=" + attempt,
            "--interactive",
            "--workdir=/workspace",
            "--env=HOME=/home/agent",
            "--env=CODEX_HOME=/home/agent/.codex",
            "--env=POLYCOLAB_DEADLINE=" + deadline.isoformat(),
        ]
        for local, target in (
            ("inputs", "/inputs"),
            ("outputs", "/outputs"),
            ("workspace", "/workspace"),
            ("home", "/home/agent"),
            ("tmp", "/tmp"),
            ("run", "/run"),
            ("shm", "/dev/shm"),
        ):
            args.extend(
                [
                    "--mount",
                    f"type=bind,src={work / local},dst={target}"
                    + (",readonly" if local == "inputs" else ""),
                ]
            )
        args.extend(["--entrypoint=python3", image.reference, "/opt/polycolab/guest_start.py"])
        return tuple(args)

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
        slot = self.reserved.get()
        if slot is None:
            raise SandboxUnavailable("physical_slot_required")
        deadline = min(deadline, datetime.now(UTC) + timedelta(seconds=limits.wall_seconds))
        attempt = uuid4().hex
        process = None
        record = self.record(attempt)
        row = {
            "version": 2,
            "backend": self.backend,
            "container": "polycolab-exec-" + attempt,
            "slot_id": int(slot.name),
            "run_id": run_id,
            "worker_id": worker_id,
            "generation": generation,
            "deadline": deadline.isoformat(),
            "limits": limits.model_dump(mode="json"),
        }
        record.parent.mkdir(mode=0o700, exist_ok=True)
        await blocking(atomic_record, record, row)
        try:
            work = await blocking(self.prepare_files, slot, inputs, limits)
            await self.host("prepare", attempt)
            # Create once. An ambiguous failure is resolved only by cleanup of this name.
            await self.docker(*self.create_args(attempt, work, image, limits, deadline))
            process = await asyncio.create_subprocess_exec(
                *self.docker_args(
                    "start", "--attach", "--interactive", "polycolab-exec-" + attempt
                ),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=2_000_000,
                env=self.environment,
            )
            channel = DockerProcess(process, attempt)
            remaining = (deadline - datetime.now(UTC)).total_seconds()
            async with asyncio.timeout(min(30, max(0, remaining))):
                if await channel.receive() != b'{"kind":"boot"}':
                    raise SandboxUnavailable("sandbox_start_failed")
                await self.host("verify", attempt)
                await channel.send(b"go\n")
                if await channel.receive() != b'{"kind":"ready"}':
                    raise SandboxUnavailable("guest_start_failed")
            yield channel, work / "outputs"
        finally:

            async def finish() -> None:
                try:
                    await self.cleanup(attempt, slot)
                except Exception:
                    self.states[int(slot.name)] = "QUARANTINED"
                    raise SlotQuarantined("sandbox_cleanup_unconfirmed") from None
                finally:
                    if process is not None:
                        if process.returncode is None:
                            process.kill()
                        await process.wait()

            task = asyncio.create_task(finish())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def stop_agent(self, process: Process) -> None:
        if not isinstance(process, DockerProcess):
            raise SandboxUnavailable("invalid_executor_process")
        await self.stop(process.attempt)
        async with asyncio.timeout(5):
            await process.wait()

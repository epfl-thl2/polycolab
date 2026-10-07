"""Microsandbox SDK adapter inside independently bounded Linux executor units.

SDK configuration and guest rlimits do not establish isolation acceptance.
Native resource, network and recovery evidence is required on the selected host.
There is no bare-host execution fallback; tests inject candidate VM handles.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from polycolab.agents.runtime.codex import CodexFailure, decode_frame
from polycolab.execution.sandbox import (
    SandboxOutput,
    SandboxResult,
    SandboxUnavailable,
    collect_outputs,
)
from polycolab.verification.contracts import ControllerClaim, ResourceLimits, validate_path

if TYPE_CHECKING:
    from microsandbox import ExecHandle, Sandbox

MICROSANDBOX_VERSION = "0.6.18"
ModelRequest = Callable[[dict[str, object]], Awaitable[bytes]]


@dataclass(frozen=True)
class ImagePolicy:
    reference: str
    language: Literal["AGENT", "PYTHON", "LEAN"]
    toolchain_version: str
    dependency_lock_digest: str
    build_digest: str
    platform_identity: str

    def __post_init__(self) -> None:
        from pydantic import TypeAdapter

        from polycolab.verification.contracts import Digest

        digest = self.reference.rsplit("@sha256:", 1)
        if len(digest) != 2 or not digest[0]:
            raise ValueError("curated image must be pinned by digest")
        TypeAdapter(Digest).validate_python(digest[1])


class Process(Protocol):
    async def send(self, data: bytes) -> None: ...
    async def receive(self) -> bytes | None: ...
    async def wait(self) -> int: ...


class SdkProcess:
    def __init__(self, handle: ExecHandle, log_bytes: int) -> None:
        self.handle = handle
        self.stdin = handle.take_stdin()
        self.log_bytes = log_bytes
        self.protocol_bytes = 32 * 1024**2
        self.pending = bytearray()

    async def send(self, data: bytes) -> None:
        if self.stdin is None:
            raise SandboxUnavailable("sandbox_stdin_unavailable")
        await self.stdin.write(data)

    async def receive(self) -> bytes | None:
        from microsandbox import ExecEventType

        while True:
            position = self.pending.find(b"\n")
            if position >= 0:
                line = bytes(self.pending[:position])
                del self.pending[: position + 1]
                return line
            event = await self.handle.recv()
            if event is None:
                if self.pending:
                    raise CodexFailure("codex_stream_incomplete")
                return None
            if event.data is not None:
                if event.event_type == ExecEventType.STDOUT:
                    self.protocol_bytes -= len(event.data)
                    if self.protocol_bytes < 0:
                        raise CodexFailure("sandbox_protocol_limit_exceeded")
                    self.pending.extend(event.data)
                    if len(self.pending) > 2_000_000:
                        raise CodexFailure("codex_frame_too_large")
                else:
                    self.log_bytes -= len(event.data)
                    if self.log_bytes < 0:
                        raise CodexFailure("sandbox_output_limit_exceeded")

    async def wait(self) -> int:
        code, _ = await self.handle.wait()
        return code


class GuestChannel:
    """Host-side framing: the guest may request only model generation or Codex I/O."""

    def __init__(self, process: Process, model: ModelRequest, max_model_requests: int) -> None:
        self.process, self.model = process, model
        self.remaining = max_model_requests
        self.last_model_id = 0

    async def send(self, message: dict[str, object]) -> None:
        await self._send("codex", message)

    async def _send(self, kind: str, payload: dict[str, object]) -> None:
        await self.process.send(json.dumps({"kind": kind, "payload": payload}).encode() + b"\n")

    async def checkpoint_repository(self) -> None:
        await self._send("repository", {})
        for _ in range(4096):
            data = await self.process.receive()
            if data is None:
                raise CodexFailure("repository_checkpoint_failed")
            frame = decode_frame(data)
            payload = frame.get("payload")
            if frame.get("kind") == "repository":
                if not isinstance(payload, dict) or not isinstance(payload.get("commit"), str):
                    raise CodexFailure("repository_checkpoint_failed")
                return
            if frame.get("kind") != "codex":
                raise CodexFailure("repository_checkpoint_failed")
        raise CodexFailure("repository_checkpoint_failed")

    async def receive(self) -> dict[str, object]:
        while True:
            data = await self.process.receive()
            if data is None:
                raise CodexFailure("codex_stream_incomplete")
            frame = decode_frame(data)
            kind, payload = frame.get("kind"), frame.get("payload")
            if not isinstance(payload, dict):
                raise CodexFailure("codex_protocol_invalid")
            if kind == "codex":
                return payload
            request_id, body = payload.get("id"), payload.get("body")
            if (
                kind != "model"
                or type(request_id) is not int
                or request_id != self.last_model_id + 1
                or not isinstance(body, dict)
            ):
                raise CodexFailure("codex_protocol_invalid")
            self.remaining -= 1
            if self.remaining < 0:
                raise CodexFailure("model_request_limit_exceeded")
            self.last_model_id = request_id
            response = await self.model(body)
            if len(response) > 1_000_000:
                raise CodexFailure("model_response_too_large")
            await self._send(
                "model",
                {
                    "id": request_id,
                    "body": base64.b64encode(response).decode("ascii"),
                },
            )


class MicrosandboxRuntime:
    def __init__(self, state_dir: Path, images: tuple[ImagePolicy, ...] = ()) -> None:
        self.state_dir = state_dir
        self.owner = hashlib.sha256(str(state_dir.resolve()).encode()).hexdigest()
        self.images = {image.reference.rsplit("@sha256:", 1)[1]: image for image in images}

    async def check_ready(self) -> None:
        from polycolab.execution.linux import isolated_executor

        isolated_executor()

    async def reconcile(self) -> None:
        await self.check_ready()
        # A dedicated host account owns this state namespace. No global prune.
        from microsandbox import Sandbox

        cursor = None
        for _page in range(100):
            page = await Sandbox.list_with(
                labels={"owner": "polycolab-execution", "controller": self.owner}, cursor=cursor
            )
            for handle in page.sandboxes:
                await handle.kill(timeout=5)
                await handle.wait_until_stopped()
                await handle.remove()
            cursor = page.next_cursor
            if cursor is None:
                return
        raise SandboxUnavailable("sandbox_reconciliation_limit_exceeded")

    @asynccontextmanager
    async def attempt(
        self,
        *,
        name: str,
        image: ImagePolicy,
        limits: ResourceLimits,
        deadline: datetime,
        inputs: dict[str, bytes],
        output_dir: Path | None = None,
    ) -> AsyncIterator[tuple[Sandbox, Path]]:
        await self.check_ready()
        from microsandbox import (
            Image,
            MountConfig,
            MountKind,
            Network,
            PullPolicy,
            RootDisk,
            Sandbox,
            SecurityProfile,
        )

        remaining = (deadline.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or version("microsandbox") != MICROSANDBOX_VERSION:
            raise SandboxUnavailable("sandbox_environment_unavailable")
        if sum(map(len, inputs.values())) > min(limits.disk_bytes, 16 * 1024 * 1024):
            raise SandboxUnavailable("sandbox_input_limit_exceeded")
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        root = Path(tempfile.mkdtemp(prefix="attempt-", dir=self.state_dir))
        source, output = root / "inputs", output_dir or root / "outputs"
        source.mkdir()
        output.mkdir(exist_ok=output_dir is not None)
        for name_in, content in inputs.items():
            validate_path(name_in)
            target = source / name_in
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        sandbox = await Sandbox.create(
            name,
            image=Image.oci(
                image.reference, root_disk=RootDisk.managed(limits.disk_bytes // (1024 * 1024))
            ),
            cpus=limits.cpu_count,
            memory=limits.memory_bytes // (1024 * 1024),
            max_duration=remaining,
            network=Network.none(),
            security=SecurityProfile.RESTRICTED,
            user="1000",
            workdir="/workspace",
            pull_policy=PullPolicy.NEVER,
            labels={"owner": "polycolab-execution", "controller": self.owner, "attempt": name},
            volumes={
                "/inputs": MountConfig(kind=MountKind.BIND, bind=str(source), readonly=True),
                "/outputs": MountConfig(
                    kind=MountKind.BIND,
                    bind=str(output),
                    nosuid=True,
                    nodev=True,
                    noexec=True,
                    override_uid=1000,
                    override_gid=1000,
                ),
            },
        )

        async def cleanup_attempt() -> None:
            try:
                async with asyncio.timeout(10):
                    await sandbox.kill(timeout=5)
                    await sandbox.wait_until_stopped()
                    await Sandbox.remove(name)
                shutil.rmtree(root)
            except Exception:
                # Preserve the staging tree when process death is uncertain.
                raise SandboxUnavailable("sandbox_cleanup_unconfirmed") from None

        try:
            remaining = (deadline.astimezone(UTC) - datetime.now(UTC)).total_seconds()
            async with asyncio.timeout(max(0, remaining)):
                yield sandbox, output
        finally:
            cleanup = asyncio.create_task(cleanup_attempt())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def run(self, claim: ControllerClaim, inputs: dict[str, bytes]) -> SandboxResult:
        await self.check_ready()
        image = self.images.get(claim.image_digest)
        if (
            image is None
            or image.language == "AGENT"
            or (
                image.toolchain_version,
                image.dependency_lock_digest,
                image.build_digest,
                image.platform_identity,
            )
            != (
                claim.toolchain_version,
                claim.dependency_lock_digest,
                claim.build_digest,
                claim.platform_identity,
            )
        ):
            raise SandboxUnavailable("sandbox_environment_unavailable")
        from microsandbox import ExecEventType, Rlimit

        submission = claim.submission
        command = "python3" if image.language == "PYTHON" else "lake"
        args = (
            ["-I", "/inputs/" + submission.entrypoint, *submission.arguments]
            if image.language == "PYTHON"
            else ["env", "lean", "/inputs/" + submission.entrypoint]
        )
        async with self.attempt(
            name=f"verification-{claim.attempt_id}-{claim.generation}",
            image=image,
            limits=submission.limits,
            deadline=claim.execution_deadline_at,
            inputs=inputs,
        ) as (sandbox, output):
            handle = await sandbox.exec_stream(
                command,
                args,
                cwd="/workspace",
                tty=False,
                env={"POLYCOLAB_OUTPUT_DIR": "/outputs", "POLYCOLAB_SEED": str(submission.seed)},
                rlimits=[
                    Rlimit.cpu(submission.limits.cpu_seconds),
                    Rlimit.nproc(submission.limits.process_count),
                ],
            )
            remaining_logs = submission.limits.log_bytes
            logs: dict[str, bytearray] = {"stdout.log": bytearray(), "stderr.log": bytearray()}
            async for event in handle:
                if event.data:
                    remaining_logs -= len(event.data)
                    if remaining_logs < 0:
                        raise SandboxUnavailable("sandbox_log_limit_exceeded")
                    name = (
                        "stdout.log" if event.event_type == ExecEventType.STDOUT else "stderr.log"
                    )
                    logs[name].extend(event.data)
            exit_code, _ = await handle.wait()
            await sandbox.kill(timeout=5)
            await sandbox.wait_until_stopped()
            outputs = collect_outputs(output, submission.limits)
            if any(item.path in logs for item in outputs):
                raise SandboxUnavailable("reserved_diagnostic_path")
            outputs += tuple(
                SandboxOutput(name, "DIAGNOSTIC", bytes(data))
                for name, data in logs.items()
                if data
            )
        return SandboxResult(
            "COMPLETED" if exit_code == 0 else "FAILED",
            exit_code,
            "NONE" if exit_code == 0 else "PROGRAM_ERROR",
            outputs,
        )

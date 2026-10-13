"""Backend-neutral hosted execution contracts and guest framing."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from polycolab.agents.runtime.codex import CodexFailure, decode_frame
from polycolab.execution.sandbox import SandboxUnavailable
from polycolab.verification.contracts import ResourceLimits

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


class SlotQuarantined(SandboxUnavailable):
    pass


class HostedRuntime(Protocol):
    backend: str
    version: str
    images: dict[str, ImagePolicy]
    states: dict[int, str]
    terminated: list[dict[str, object]]

    async def check_ready(self) -> None: ...
    async def reconcile(self) -> None: ...
    def reserve(self) -> AbstractAsyncContextManager[int | None]: ...
    def agent(
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
    ) -> AbstractAsyncContextManager[tuple[Process, Path]]: ...
    async def stop_agent(self, process: Process) -> None: ...
    def acknowledge(self, run_id: str, generation: int) -> None: ...

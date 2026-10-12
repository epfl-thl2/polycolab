"""Bounded, cancellable private API transport for the hosted controller."""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from polycolab.agents.runtime.remote import RuntimeClaim, RuntimeGatewayError


class ClaimEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    lease_generation: int = Field(ge=1)
    model_id: str
    messages: list[dict[str, Any]]
    tool_capability: str
    max_output_tokens: int = Field(ge=1)
    max_model_rounds: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_tool_argument_bytes: int = Field(ge=1)
    max_tool_result_bytes: int = Field(ge=1)
    lease_seconds: int = Field(ge=1)
    deadline_at: datetime
    runtime_spec: dict[str, Any]
    tools: list[dict[str, Any]]
    input_manifest: list[dict[str, Any]] = Field(default_factory=list)
    server_time: datetime | None = None
    repository: dict[str, str] | None = None


class RuntimeClient:
    def __init__(
        self, base_url: str, token: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.incarnation = str(uuid4())
        url = httpx.URL(base_url)
        try:
            local = ipaddress.ip_address(url.host).is_loopback
        except ValueError:
            local = url.host == "localhost"
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (url.scheme == "http" and not local)
        ):
            raise ValueError("private API requires HTTPS or loopback HTTP")
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "identity"},
            trust_env=False,
            follow_redirects=False,
            timeout=30,
            transport=transport,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> Any:
        retryable = path.rsplit("/", 1)[-1] in {"lease", "terminated", "finish", "readiness"}
        deadline = asyncio.get_running_loop().time() + timeout
        for attempt in range(3):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise RuntimeGatewayError("runtime_api_unavailable")
            try:
                return await self._post_once(path, payload, headers=headers, timeout=remaining)
            except RuntimeGatewayError as exc:
                if (
                    not retryable
                    or exc.code not in {"runtime_api_unavailable", "runtime_api_failed"}
                    or attempt == 2
                ):
                    raise
                await asyncio.sleep(
                    min(0.25 * 2**attempt, max(0, deadline - asyncio.get_running_loop().time()))
                )
        raise RuntimeGatewayError("runtime_api_unavailable")

    async def _post_once(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> Any:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        if len(body) > 400_000:
            raise RuntimeGatewayError("runtime_request_too_large")
        try:
            async with asyncio.timeout(timeout):
                async with self.client.stream(
                    "POST",
                    path,
                    content=body,
                    timeout=httpx.Timeout(timeout, connect=min(5, timeout)),
                    headers={"Content-Type": "application/json", **(headers or {})},
                ) as response:
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise RuntimeGatewayError("runtime_api_invalid")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 2_000_000:
                            raise RuntimeGatewayError("runtime_response_too_large")
                        data.extend(chunk)
                    if response.status_code == 204:
                        return None
                    if response.status_code in {401, 403, 404}:
                        raise RuntimeGatewayError("authority_or_lease_lost")
                    if response.status_code >= 500:
                        raise RuntimeGatewayError("runtime_api_failed")
                    value = json.loads(data)
                    if response.status_code == 409:
                        code = (
                            value.get("error", {}).get("code", "lease_lost")
                            if isinstance(value, dict)
                            else "lease_lost"
                        )
                        raise RuntimeGatewayError(code if isinstance(code, str) else "lease_lost")
                    if response.status_code != 200:
                        raise RuntimeGatewayError("runtime_api_failed")
                    return value
        except httpx.HTTPError, TimeoutError:
            raise RuntimeGatewayError("runtime_api_unavailable") from None
        except ValueError, TypeError, AttributeError:
            raise RuntimeGatewayError("runtime_api_invalid") from None

    async def claim(self, worker_id: str, *, slot_id: int | None = None) -> RuntimeClaim | None:
        value = await self.post(
            "/internal/v1/runtime/claims",
            {
                "worker_id": worker_id,
                "engine": "codex",
                "incarnation": self.incarnation,
                "slot_id": slot_id,
                "protocol_version": 4,
            },
        )
        if value is None:
            return None
        envelope = ClaimEnvelope.model_validate(value)
        if envelope.server_time is not None and (
            envelope.server_time.tzinfo is None
            or abs((datetime.now(UTC) - envelope.server_time).total_seconds()) > 5
        ):
            raise RuntimeGatewayError("host_clock_skew")
        if envelope.deadline_at.tzinfo is None:
            raise RuntimeGatewayError("runtime_api_invalid")
        fields = envelope.model_dump(exclude={"lease_seconds"})
        return RuntimeClaim(**fields, lease_for=timedelta(seconds=envelope.lease_seconds))

    async def lease(self, claim: RuntimeClaim, worker_id: str, action: str, **payload: Any) -> Any:
        return await self.post(
            f"/internal/v1/runtime/runs/{claim.run_id}/{action}",
            {
                "worker_id": worker_id,
                "engine": "codex",
                "lease_generation": claim.lease_generation,
                **payload,
            },
            timeout=60 if action == "responses" else 30,
        )

    async def responses(
        self, claim: RuntimeClaim, worker_id: str, body: dict[str, object], request_id: str
    ) -> bytes:
        value = await self.lease(claim, worker_id, "responses", body=body, request_id=request_id)
        try:
            return base64.b64decode(value["body"], validate=True)
        except ValueError, TypeError, KeyError:
            raise RuntimeGatewayError("runtime_api_invalid") from None

    async def tool(
        self,
        claim: RuntimeClaim,
        name: str,
        arguments: dict[str, object],
        invocation: str,
        cursor: int,
    ) -> dict[str, object]:
        value = await self.post(
            "/internal/v1/tools/call",
            {"name": name, "arguments": arguments},
            headers={
                "Authorization": f"Bearer {claim.tool_capability}",
                "X-Polycolab-Tool-Invocation": invocation,
                "X-Polycolab-Source-Event-Cursor": str(cursor),
            },
        )
        if not isinstance(value, dict):
            raise RuntimeGatewayError("tool_gateway_invalid")
        return value

    async def artifact_bytes(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        *,
        content: bytes | None = None,
        limit: int = 16 * 1024**2,
    ) -> bytes:
        try:
            async with asyncio.timeout(30):
                async with self.client.stream(
                    method, path, params=params, content=content
                ) as response:
                    if response.status_code != 200:
                        raise RuntimeGatewayError("artifact_transport_failed")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > limit:
                            raise RuntimeGatewayError("artifact_size_limit")
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError, TimeoutError:
            raise RuntimeGatewayError("artifact_transport_unavailable") from None

    async def inputs(self, claim: RuntimeClaim, worker_id: str) -> dict[str, bytes]:
        import hashlib

        result: dict[str, bytes] = {}
        for item in claim.input_manifest:
            artifact_id = str(UUID(str(item["id"])))
            size = int(str(item["byte_length"]))
            if size < 0 or sum(map(len, result.values())) + size > 16 * 1024**2:
                raise RuntimeGatewayError("artifact_size_limit")
            data = await self.artifact_bytes(
                "GET",
                f"/internal/hosted/runs/{claim.run_id}/inputs/{artifact_id}",
                {"worker_id": worker_id, "lease_generation": claim.lease_generation},
                limit=size,
            )
            if len(data) != size or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise RuntimeGatewayError("artifact_integrity_mismatch")
            result[artifact_id] = data
        if claim.repository is not None:
            data = await self.artifact_bytes(
                "GET",
                f"/internal/hosted/runs/{claim.run_id}/repository",
                {"worker_id": worker_id, "lease_generation": claim.lease_generation},
            )
            metadata = json.dumps(claim.repository).encode()
            if sum(map(len, result.values())) + len(data) + len(metadata) > 16 * 1024**2:
                raise RuntimeGatewayError("repository_size_limit")
            result["workspace.bundle"] = data
            result["workspace.json"] = metadata
        return result

    async def save_repository(self, claim: RuntimeClaim, worker_id: str, data: bytes) -> None:
        try:
            await self.artifact_bytes(
                "POST",
                f"/internal/hosted/runs/{claim.run_id}/repository",
                {"worker_id": worker_id, "lease_generation": claim.lease_generation},
                content=data,
                limit=4096,
            )
        except RuntimeGatewayError as exc:
            raise RuntimeGatewayError("repository_save_failed") from exc

    async def export(
        self, claim: RuntimeClaim, worker_id: str, declaration: dict[str, Any], data: bytes
    ) -> None:
        import hashlib

        await self.artifact_bytes(
            "POST",
            f"/internal/hosted/runs/{claim.run_id}/artifacts",
            {
                "worker_id": worker_id,
                "lease_generation": claim.lease_generation,
                **declaration,
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_length": len(data),
            },
            content=data,
            limit=4096,
        )

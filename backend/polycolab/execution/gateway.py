"""Database-free private verification client with bounded, same-origin transfers."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from polycolab.verification.contracts import (
    AttemptBinding,
    ControllerClaim,
    ControllerCompletion,
    JobRead,
    OutputReference,
    OutputStageRequest,
)
from polycolab.verification.version_contracts import VersionControllerClaim, VersionJobRead


class ExecutionGatewayError(Exception):
    """Normalized codes only: never include URLs, tokens, bodies or input source."""


def binding(claim: AttemptBinding) -> dict[str, object]:
    return {
        "job_id": str(claim.job_id),
        "attempt_id": str(claim.attempt_id),
        "generation": claim.generation,
    }


class ExecutionGateway:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        request_bytes: int = 262_144,
        response_bytes: int = 1_000_000,
        timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        url = urlsplit(base_url)
        try:
            local = ipaddress.ip_address(url.hostname or "").is_loopback
        except ValueError:
            local = url.hostname == "localhost"
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (url.scheme == "http" and not local)
        ):
            raise ValueError("controller API requires HTTPS or explicit loopback HTTP")
        if not token or len(token) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ValueError("explicit controller credential required")
        if (
            not 1 <= request_bytes <= 10_000_000
            or not 1 <= response_bytes <= 20_000_000
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("invalid controller transport bounds")
        self.request_bytes = request_bytes
        self.response_bytes = response_bytes
        self.timeout_seconds = timeout_seconds
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        params: dict[str, str | int] | None = None,
        ceiling: int | None = None,
        binary: bool = False,
    ) -> bytes:
        limit = self.response_bytes if ceiling is None else ceiling
        if body is not None and len(body) > (16 * 1024 * 1024 if binary else self.request_bytes):
            raise ExecutionGatewayError("request_too_large")
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self.client.stream(
                    method,
                    path,
                    content=body,
                    params=params,
                    headers={
                        "Content-Type": "application/octet-stream"
                        if binary
                        else "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    if response.status_code in {401, 403, 404, 409}:
                        raise ExecutionGatewayError("authority_or_lease_lost")
                    if response.status_code != 200:
                        raise ExecutionGatewayError("private_api_unavailable")
                    if response.headers.get("content-encoding", "identity") != "identity":
                        raise ExecutionGatewayError("unexpected_content_encoding")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > limit:
                            raise ExecutionGatewayError("response_too_large")
                        data.extend(chunk)
                    return bytes(data)
        except httpx.HTTPError, TimeoutError:
            raise ExecutionGatewayError("private_api_unavailable") from None

    async def _json(self, path: str, payload: dict[str, object] | None = None) -> object:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        data = await self._request("POST", path, body=body)
        try:
            return json.loads(data)
        except ValueError, UnicodeError:
            raise ExecutionGatewayError("invalid_private_response") from None

    async def claim(self) -> ControllerClaim | None:
        value = await self._json("/internal/verification/claim")
        if value is None:
            return None
        try:
            return VersionControllerClaim.model_validate(value).historical_value()
        except ValidationError:
            raise ExecutionGatewayError("invalid_private_response") from None

    async def renew(self, claim: ControllerClaim) -> ControllerClaim:
        value = await self._json("/internal/verification/renew", binding(claim))
        try:
            renewed = VersionControllerClaim.model_validate(value).historical_value()
        except ValidationError:
            raise ExecutionGatewayError("invalid_private_response") from None
        if renewed.model_dump(exclude={"lease_expires_at"}) != claim.model_dump(
            exclude={"lease_expires_at"}
        ):
            raise ExecutionGatewayError("claim_identity_changed")
        return renewed

    async def inputs(self, claim: ControllerClaim) -> dict[str, bytes]:
        # This initial controller uses an in-memory staging set, capped separately
        # from the much larger admitted sandbox disk. A disk-backed adapter comes
        # with the Linux launcher; never allocate the full sandbox disk in RAM.
        remaining = min(claim.submission.limits.disk_bytes, 16 * 1024 * 1024)
        result: dict[str, bytes] = {}
        manifest = []
        for position, item in enumerate(claim.submission.inputs):
            data = await self._request(
                "GET",
                f"/internal/verification/jobs/{claim.job_id}/attempts/{claim.attempt_id}/inputs/{position}",
                params={"generation": claim.generation},
                ceiling=min(remaining, 16 * 1024 * 1024),
            )
            remaining -= len(data)
            result[item.path] = data
            manifest.append(
                {"input": item.model_dump(mode="json"), "sha256": hashlib.sha256(data).hexdigest()}
            )
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
        if digest != claim.manifest_digest:
            raise ExecutionGatewayError("input_manifest_mismatch")
        return result

    async def stage(
        self, claim: ControllerClaim, *, path: str, role: str, data: bytes
    ) -> OutputReference:
        declaration = OutputStageRequest.model_validate(
            {
                **binding(claim),
                "path": path,
                "role": role,
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_length": len(data),
            }
        )
        response = await self._request(
            "PUT",
            f"/internal/verification/jobs/{claim.job_id}/attempts/{claim.attempt_id}/outputs",
            body=data,
            binary=True,
            params={
                "generation": claim.generation,
                "path": declaration.path,
                "role": declaration.role,
                "sha256": declaration.sha256,
                "byte_length": declaration.byte_length,
            },
        )
        try:
            value = json.loads(response)
            if not isinstance(value, dict) or set(value) != {"artifact_id"}:
                raise ValueError
            artifact_id = UUID(value["artifact_id"])
        except ValueError, TypeError, UnicodeError, AttributeError:
            raise ExecutionGatewayError("invalid_private_response") from None
        return OutputReference.model_validate(
            {
                "artifact_id": artifact_id,
                "path": path,
                "role": role,
                "sha256": declaration.sha256,
                "byte_length": declaration.byte_length,
            }
        )

    async def complete(self, payload: ControllerCompletion) -> JobRead:
        value = await self._json("/internal/verification/complete", payload.model_dump(mode="json"))
        try:
            result = VersionJobRead.model_validate(value).historical_value()
        except ValidationError:
            raise ExecutionGatewayError("invalid_private_response") from None
        if (
            result.id != payload.job_id
            or result.generation != payload.generation
            or result.state != payload.outcome
        ):
            raise ExecutionGatewayError("completion_identity_changed")
        return result

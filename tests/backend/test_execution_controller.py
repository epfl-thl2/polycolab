"""Mock transport/runtime evidence only; never claims Linux isolation acceptance."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from polycolab.execution.controller import ExecutionController
from polycolab.execution.gateway import ExecutionGateway, ExecutionGatewayError
from polycolab.execution.sandbox import (
    SandboxResult,
    SandboxUnavailable,
    UnsafeSandboxOutput,
    collect_outputs,
)
from polycolab.verification.contracts import (
    ControllerClaim,
    InputReference,
    JobPurpose,
    JobRead,
    JobSubmission,
    ResourceLimits,
)
from polycolab.verification.version_contracts import VersionControllerClaim, VersionJobRead


def claim_value(seconds: float = 30) -> ControllerClaim:
    source = InputReference(path="main.py", role="SOURCE", revision_id=uuid4())
    manifest = [
        {"input": source.model_dump(mode="json"), "sha256": hashlib.sha256(b"print(1)").hexdigest()}
    ]
    limits = ResourceLimits(
        cpu_count=1,
        cpu_seconds=1,
        wall_seconds=10,
        memory_bytes=16 * 1024 * 1024,
        process_count=4,
        disk_bytes=1024 * 1024,
        output_bytes=32,
        log_bytes=16,
        output_files=3,
    )
    return ControllerClaim(
        job_id=uuid4(),
        attempt_id=uuid4(),
        generation=1,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        execution_deadline_at=datetime.now(UTC) + timedelta(seconds=10),
        submission=JobSubmission(
            project_id=uuid4(),
            work_target_revision_id=uuid4(),
            environment_id=uuid4(),
            purpose=JobPurpose.PYTHON_RUN,
            evidence_scope="mock test",
            inputs=(source,),
            entrypoint="main.py",
            limits=limits,
        ),
        manifest_digest=hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest(),
        image_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        build_digest="c" * 64,
        toolchain_version="test-only",
        platform_identity="test-only",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://u:p@example.com",
        "https://example.com/path",
        "https://example.com?token=x",
    ],
)
def test_private_origin_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        ExecutionGateway(url, "test-secret")


def test_gateway_verifies_manifest_and_caps_response() -> None:
    async def run() -> None:
        claim = claim_value()

        def respond(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == "Bearer test-secret"
            return httpx.Response(200, content=b"print(1)")

        gateway = ExecutionGateway(
            "http://127.0.0.1", "test-secret", transport=httpx.MockTransport(respond)
        )
        try:
            assert await gateway.inputs(claim) == {"main.py": b"print(1)"}
            with pytest.raises(ExecutionGatewayError, match="input_manifest_mismatch"):
                await gateway.inputs(claim.model_copy(update={"manifest_digest": "0" * 64}))
            with pytest.raises(ExecutionGatewayError, match="response_too_large"):
                await gateway._request("GET", "/bounded", ceiling=2)
        finally:
            await gateway.close()

    asyncio.run(run())


@pytest.mark.parametrize("status", [302, 401, 403, 404, 409, 500])
def test_gateway_never_follows_redirects_or_echoes_errors(status: int) -> None:
    async def run() -> None:
        seen = []

        def respond(request: httpx.Request) -> httpx.Response:
            seen.append(request.url)
            return httpx.Response(
                status, headers={"location": "https://elsewhere.test"}, text="SECRET SOURCE"
            )

        gateway = ExecutionGateway(
            "http://127.0.0.1", "test-secret", transport=httpx.MockTransport(respond)
        )
        try:
            with pytest.raises(ExecutionGatewayError) as error:
                await gateway.claim()
            assert "SECRET" not in str(error.value) and len(seen) == 1
        finally:
            await gateway.close()

    asyncio.run(run())


class FakeRuntime:
    def __init__(self, *, ready: bool = True, wait: bool = False) -> None:
        self.ready = ready
        self.wait = wait
        self.stopped = False
        self.ran = False

    async def check_ready(self) -> None:
        if not self.ready:
            raise SandboxUnavailable

    async def reconcile(self) -> None:
        pass

    async def run(self, claim: ControllerClaim, inputs: dict[str, bytes]) -> SandboxResult:
        self.ran = True
        assert inputs == {"main.py": b"print(1)"}
        try:
            if self.wait:
                await asyncio.Event().wait()
            return SandboxResult("COMPLETED", 0, "NONE")
        finally:
            self.stopped = True


def test_unavailable_runtime_does_not_claim() -> None:
    async def run() -> None:
        def unexpected(request: httpx.Request) -> httpx.Response:
            raise AssertionError("must not claim")

        gateway = ExecutionGateway(
            "http://127.0.0.1", "test-secret", transport=httpx.MockTransport(unexpected)
        )
        try:
            with pytest.raises(SandboxUnavailable):
                await ExecutionController(gateway, FakeRuntime(ready=False)).once()
        finally:
            await gateway.close()

    asyncio.run(run())


def test_lease_loss_cancels_runtime_without_completion() -> None:
    async def run() -> None:
        claim = claim_value(0.15)
        runtime = FakeRuntime(wait=True)
        completed = []

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/claim"):
                return httpx.Response(
                    200, json=VersionControllerClaim.from_stored(claim).model_dump(mode="json")
                )
            if "/inputs/" in request.url.path:
                return httpx.Response(200, content=b"print(1)")
            if request.url.path.endswith("/renew"):
                return httpx.Response(409)
            completed.append(request.url.path)
            raise AssertionError("must not complete")

        gateway = ExecutionGateway(
            "http://127.0.0.1", "test-secret", transport=httpx.MockTransport(respond)
        )
        try:
            with pytest.raises(ExecutionGatewayError, match="authority_or_lease_lost"):
                await ExecutionController(gateway, runtime).once()
            assert runtime.ran and runtime.stopped and not completed
        finally:
            await gateway.close()

    asyncio.run(run())


def test_controller_completion_retries_identical_payload_only() -> None:
    async def run() -> None:
        claim = claim_value()
        completions = []

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/claim"):
                return httpx.Response(
                    200, json=VersionControllerClaim.from_stored(claim).model_dump(mode="json")
                )
            if "/inputs/" in request.url.path:
                return httpx.Response(200, content=b"print(1)")
            completions.append(request.content)
            if len(completions) == 1:
                return httpx.Response(503)
            result = JobRead(
                id=claim.job_id,
                submission=claim.submission,
                manifest_digest=claim.manifest_digest,
                state="COMPLETED",
                generation=claim.generation,
                event_sequence=3,
                deadline_at=claim.execution_deadline_at,
                terminal_reason="NONE",
                attempts=(),
                results=(),
            )
            return httpx.Response(
                200, json=VersionJobRead.from_stored(result).model_dump(mode="json")
            )

        gateway = ExecutionGateway(
            "http://127.0.0.1", "test-secret", transport=httpx.MockTransport(respond)
        )
        try:
            assert await ExecutionController(gateway, FakeRuntime()).once()
            assert len(completions) == 2 and completions[0] == completions[1]
        finally:
            await gateway.close()

    asyncio.run(run())


def test_output_collector_limits_and_links(tmp_path: Path) -> None:
    limits = claim_value().submission.limits
    (tmp_path / "value.txt").write_bytes(b"value")
    (tmp_path / "stdout.log").write_bytes(b"log")
    output = collect_outputs(tmp_path, limits)
    assert [item.role for item in output] == ["DIAGNOSTIC", "OUTPUT"]
    with pytest.raises(UnsafeSandboxOutput):
        collect_outputs(tmp_path, limits.model_copy(update={"output_files": 1}))
    with pytest.raises(UnsafeSandboxOutput):
        collect_outputs(tmp_path, limits.model_copy(update={"log_bytes": 0}))
    (tmp_path / "escape").symlink_to(tmp_path / "value.txt")
    with pytest.raises(UnsafeSandboxOutput):
        collect_outputs(tmp_path, limits)


def test_controller_dependency_boundary() -> None:
    import ast

    package = Path(__file__).resolve().parents[2] / "src/backend" / "polycolab"
    for name in (
        "execution/controller.py",
        "execution/gateway.py",
        "execution/sandbox.py",
        "verification/contracts.py",
    ):
        tree = ast.parse((package / name).read_text())
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            assert not any(
                module.startswith(
                    (
                        "sqlalchemy",
                        "polycolab.db.session",
                        "polycolab.db.models",
                        "polycolab.platform.config",
                        "polycolab.verification.tools",
                    )
                )
                for module in modules
            )

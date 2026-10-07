"""Hosted Codex supervision; no model loop, database, or guest-owned authority."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from pydantic import ValidationError

from polycolab.agents.runtime.artifacts import EXPORT_TOOL, ExportDeclaration
from polycolab.agents.runtime.client import RuntimeClient
from polycolab.agents.runtime.codex import CodexFailure, CodexSession, CodexTask
from polycolab.agents.runtime.remote import (
    RuntimeClaim,
    RuntimeGatewayError,
    WorkerTerminalStatus,
)
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.execution.linux import LinuxRuntime, SlotQuarantined
from polycolab.execution.microsandbox import GuestChannel
from polycolab.execution.sandbox import SandboxUnavailable, UnsafeSandboxOutput, collect_outputs


class AgentController:
    def __init__(
        self,
        gateway: RuntimeClient,
        runtime: LinuxRuntime,
        worker_id: str,
    ) -> None:
        self.gateway, self.runtime, self.worker_id = gateway, runtime, worker_id

    async def once(self) -> bool:
        await self.runtime.check_ready()
        async with self.runtime.reserve() as slot_id:
            if slot_id is None:
                return False
            try:
                claim = await self.gateway.claim(self.worker_id, slot_id=slot_id)
                if claim is None:
                    return False
                await self.execute(claim)
            except SlotQuarantined:
                return True
            except RuntimeGatewayError as exc:
                if exc.code in {
                    "authority_or_lease_lost",
                    "executor_incarnation_conflict",
                    "executor_protocol_mismatch",
                    "host_clock_skew",
                }:
                    raise
                # API uncertainty or a lost fence is isolated to this attempt.
                # The durable API reconciler decides whether user resume is required.
                return False
        return True

    async def execute(self, claim: RuntimeClaim) -> None:
        if claim.runtime_spec is None or claim.deadline_at is None:
            await self._finish(claim, "FAILED", "runtime_spec_missing")
            return
        try:
            spec = RuntimeSpec.model_validate(claim.runtime_spec)
        except ValidationError:
            await self._finish(claim, "FAILED", "runtime_spec_invalid")
            return
        image = self.runtime.images.get(spec.image.rsplit("@sha256:", 1)[1])
        if (
            image is None
            or image.language != "AGENT"
            or image.toolchain_version != spec.engine_version
        ):
            await self._finish(claim, "FAILED", "sandbox_environment_unavailable")
            return
        remaining = (claim.deadline_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            await self._finish(claim, "TIMED_OUT", "deadline_exceeded")
            return
        result: str | None = None
        status: WorkerTerminalStatus = "COMPLETED"
        failure: str | None = None
        prefix = f"codex-{claim.lease_generation}-"

        model_ordinal = 0
        exports: dict[str, ExportDeclaration] = {}

        lease_deadline = asyncio.get_running_loop().time() + min(
            claim.lease_for.total_seconds(), remaining
        )

        async def checkpoint() -> None:
            nonlocal lease_deadline
            started = asyncio.get_running_loop().time()
            budget = max(0, lease_deadline - started - 2)
            try:
                async with asyncio.timeout(budget):
                    await self._checkpoint(claim)
            except TimeoutError:
                raise RuntimeGatewayError("lease_lost") from None
            lease_deadline = started + claim.lease_for.total_seconds()

        async def heartbeat_loop() -> None:
            while True:
                await checkpoint()
                await asyncio.sleep(max(0.1, claim.lease_for.total_seconds() / 3))

        async def event(key: str, kind: str, payload: dict[str, object]) -> int:
            result = await self.gateway.lease(
                claim,
                self.worker_id,
                "events",
                idempotency_key=prefix + key,
                kind=kind,
                payload=payload,
            )
            cursor = result.get("cursor")
            if type(cursor) is not int or cursor < 1:
                raise CodexFailure("runtime_api_invalid")
            return cursor

        async def tool(
            name: str, arguments: dict[str, object], invocation: str, cursor: int
        ) -> dict[str, object]:
            await checkpoint()
            if name == "export_artifact":
                try:
                    declaration = ExportDeclaration.model_validate(arguments)
                except ValidationError:
                    return {"error": "invalid_export_declaration"}
                if declaration.path == "workspace.bundle":
                    return {"error": "reserved_output_path"}
                if declaration.path not in exports and len(exports) >= spec.limits.output_files:
                    return {"error": "artifact_output_limit"}
                exports[declaration.path] = declaration
                return {"registered": declaration.path}
            return await self.gateway.tool(claim, name, arguments, prefix + invocation, cursor)

        async def model(body: dict[str, object]) -> bytes:
            nonlocal model_ordinal
            await checkpoint()
            model_ordinal += 1
            return await self.gateway.responses(
                claim, self.worker_id, body, prefix + f"model-{model_ordinal}"
            )

        deadline = claim.deadline_at

        async def run() -> str:
            inputs = await self.gateway.inputs(claim, self.worker_id)
            async with self.runtime.agent(
                name=f"agent-{claim.run_id}-{claim.lease_generation}",
                image=image,
                limits=spec.limits,
                deadline=deadline,
                inputs=inputs,
                run_id=str(claim.run_id),
                generation=claim.lease_generation,
                worker_id=self.worker_id,
            ) as (process, output):
                channel = GuestChannel(process, model, spec.max_model_requests)
                task = CodexTask(
                    claim.model_id,
                    [
                        *claim.messages,
                        {
                            "role": "system",
                            "content": (
                                "Read-only artifact inputs are mounted at /inputs/<artifact UUID>. "
                                "Available input filenames: " + ", ".join(sorted(inputs)) + ". "
                                "Write downloadable files under /outputs and register each with "
                                "export_artifact. "
                                + (
                                    "On success, /workspace is saved to your session branch. "
                                    "Keep the checkout on its original branch. Integrate subagent "
                                    "worktrees before finishing. Ignored files are not saved."
                                    if claim.repository is not None
                                    else "Other workspace files are discarded after this turn."
                                )
                            ),
                        },
                    ],
                    [*claim.tools, EXPORT_TOOL],
                    max_tool_calls=claim.max_tool_calls,
                    max_argument_bytes=claim.max_tool_argument_bytes,
                    max_result_bytes=claim.max_tool_result_bytes,
                )
                answer = await CodexSession(channel, task, event, tool).run()
                if claim.repository is not None:
                    await channel.checkpoint_repository()
                await self.runtime.stop_agent(process)
                selected = set(exports) | (
                    {"workspace.bundle"} if claim.repository is not None else set()
                )
                files = collect_outputs(output, spec.limits, selected=selected)
                if {item.path for item in files} != selected:
                    raise CodexFailure("artifact_export_missing")
            for item in files:
                await checkpoint()
                if item.path == "workspace.bundle":
                    await self.gateway.save_repository(claim, self.worker_id, item.data)
                else:
                    await self.gateway.export(
                        claim, self.worker_id, exports[item.path].model_dump(), item.data
                    )
            return answer

        work = asyncio.create_task(run())
        heartbeat = asyncio.create_task(heartbeat_loop())
        try:
            async with asyncio.timeout(remaining):
                done, _ = await asyncio.wait((work, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                if heartbeat in done:
                    await heartbeat
                result = await work
        except TimeoutError:
            status, failure = "TIMED_OUT", "deadline_exceeded"
        except SlotQuarantined:
            raise
        except SandboxUnavailable:
            status, failure = "FAILED", "sandbox_environment_unavailable"
        except UnsafeSandboxOutput, OSError:
            status, failure = "FAILED", "artifact_output_invalid"
        except RuntimeGatewayError as exc:
            if exc.code in {
                "runtime_api_unavailable",
                "runtime_api_failed",
                "lease_lost",
                "authority_or_lease_lost",
                "authorization_revoked",
            }:
                raise
            status, failure = "FAILED", exc.code
            if failure in {"provider_request_uncertain", "model_request_already_dispatched"}:
                failure = "provider_uncertain_resume_required"
        except CodexFailure as exc:
            if str(exc) == "cancel_requested":
                status = "CANCELLED"
            elif str(exc) == "deadline_exceeded":
                status, failure = "TIMED_OUT", "deadline_exceeded"
            else:
                status, failure = "FAILED", str(exc)
        finally:
            work.cancel()
            heartbeat.cancel()
            results = await asyncio.gather(work, heartbeat, return_exceptions=True)
            # A failed VM stop must not look like successful cancellation/completion.
            if isinstance(results[0], SlotQuarantined):
                raise results[0]
        # Finalize only after cleanup; API uncertainty leaves recovery to the reconciler.
        await self._finish(claim, status, failure, result)

    async def _checkpoint(self, claim: RuntimeClaim) -> None:
        state = await self.gateway.lease(claim, self.worker_id, "lease")
        if state.get("active") is not True:
            raise CodexFailure("lease_lost")
        if state.get("timed_out"):
            raise CodexFailure("deadline_exceeded")
        if state.get("cancel_requested"):
            raise CodexFailure("cancel_requested")

    async def _finish(
        self,
        claim: RuntimeClaim,
        status: WorkerTerminalStatus,
        failure: str | None,
        text: str | None = None,
    ) -> None:
        await self.gateway.lease(claim, self.worker_id, "terminated")
        await self.gateway.lease(
            claim,
            self.worker_id,
            "finish",
            status=status,
            failure_code=failure,
            final_message_md=text,
        )
        self.runtime.acknowledge(str(claim.run_id), claim.lease_generation)

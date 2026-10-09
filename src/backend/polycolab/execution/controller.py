"""Database-free orchestration core. No default/runtime fallback is provided."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from polycolab.execution.gateway import ExecutionGateway, ExecutionGatewayError, binding
from polycolab.execution.sandbox import SandboxRuntime, SandboxUnavailable
from polycolab.verification.contracts import (
    ControllerClaim,
    ControllerCompletion,
    validate_completion_limits,
)


def _remaining(value: datetime) -> float:
    if value.tzinfo is None:
        raise ExecutionGatewayError("invalid_lease_timestamp")
    return (value - datetime.now(UTC)).total_seconds()


class ExecutionController:
    """One bounded attempt at a time, with independently supervised lease renewal.

    The runtime receives no API object/token or ambient controller configuration.
    The runtime adapter must kill/wait on cancellation, and independently enforce
    the API's absolute deadline even if this controller process disappears.
    """

    def __init__(self, gateway: ExecutionGateway, runtime: SandboxRuntime) -> None:
        self.gateway = gateway
        self.runtime = runtime

    async def once(self) -> bool:
        await self.runtime.check_ready()
        await self.runtime.reconcile()
        claim = await self.gateway.claim()
        if claim is None:
            return False
        lease = [_remaining(claim.lease_expires_at)]
        if lease[0] <= 0 or _remaining(claim.execution_deadline_at) <= 0:
            raise ExecutionGatewayError("expired_claim")
        loop = asyncio.get_running_loop()
        lease[0] += loop.time()
        work = asyncio.create_task(self._execute(claim))
        heartbeat = asyncio.create_task(self._heartbeat(claim, lease))
        try:
            async with asyncio.timeout(_remaining(claim.execution_deadline_at)):
                done, _ = await asyncio.wait((work, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                # Lease loss always wins if both tasks finish in the same turn.
                if heartbeat in done:
                    await heartbeat
                    raise ExecutionGatewayError("lease_supervision_stopped")
                await work
                return True
        finally:
            work.cancel()
            heartbeat.cancel()
            results = await asyncio.gather(work, heartbeat, return_exceptions=True)
            if isinstance(results[0], SandboxUnavailable):
                raise results[0]

    async def _heartbeat(self, claim: ControllerClaim, lease: list[float]) -> None:
        loop = asyncio.get_running_loop()
        while True:
            remaining = lease[0] - loop.time()
            if remaining <= 0:
                raise ExecutionGatewayError("lease_expired")
            await asyncio.sleep(min(5, remaining / 3))
            # No retry grace after a failed heartbeat: stop the sandbox first.
            async with asyncio.timeout(max(0, lease[0] - loop.time())):
                updated = await self.gateway.renew(claim)
            remaining = min(
                _remaining(updated.lease_expires_at), _remaining(claim.execution_deadline_at)
            )
            if remaining <= 0:
                raise ExecutionGatewayError("lease_expired")
            lease[0] = loop.time() + remaining

    async def _execute(self, claim: ControllerClaim) -> None:
        inputs = await self.gateway.inputs(claim)
        result = await self.runtime.run(claim, inputs)
        # Validate all paths/counts/bytes before uploading any outputs.
        import hashlib
        from uuid import uuid4

        from polycolab.verification.contracts import OutputReference

        declared = tuple(
            OutputReference.model_validate(
                {
                    "artifact_id": uuid4(),
                    "path": output.path,
                    "role": output.role,
                    "sha256": hashlib.sha256(output.data).hexdigest(),
                    "byte_length": len(output.data),
                }
            )
            for output in result.outputs
        )
        completion = ControllerCompletion.model_validate(
            {
                **binding(claim),
                "outcome": result.outcome,
                "exit_code": result.exit_code,
                "diagnostic_code": result.diagnostic_code,
                "outputs": declared,
            }
        )
        validate_completion_limits(completion, claim.submission.limits)
        outputs = []
        for output in result.outputs:
            outputs.append(
                await self.gateway.stage(
                    claim, path=output.path, role=output.role, data=output.data
                )
            )
        payload = completion.model_copy(update={"outputs": tuple(outputs)})
        # A single identical replay handles an ambiguous completion response;
        # no claim/launch retry is hidden in the transport.
        try:
            await self.gateway.complete(payload)
        except ExecutionGatewayError as error:
            if str(error) != "private_api_unavailable":
                raise
            await self.gateway.complete(payload)

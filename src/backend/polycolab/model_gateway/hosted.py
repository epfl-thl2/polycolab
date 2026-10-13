"""API-owned hosted dispatch reservations and settlement, including lost leases."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.agents.runtime.spec import RuntimeSpec
from polycolab.agents.sessions import _append_event_locked, _require_live_lease
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunUsage,
    SqlGatewayProfile,
    SqlHostedModelRequest,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus, UsageSource
from polycolab.entities.time import utc_now
from polycolab.execution.allocator import utc
from polycolab.execution.limits import _lock_scopes
from polycolab.model_gateway import async_transport
from polycolab.model_gateway.credentials import (
    CredentialError,
    EncryptedCredential,
    credential_context,
    decrypt_credential,
)
from polycolab.model_gateway.responses import (
    IncompleteResponse,
    completed_response,
    validated_request,
)
from polycolab.model_gateway.service import ProviderFailure
from polycolab.model_gateway.transport import ProviderTransportError
from polycolab.platform.observability import increment_durable


def settle(session: Session, request_id: UUID, usage: dict[str, int] | None) -> None:
    """Provider observations use API dispatch authority, never a worker's stale fence."""
    entry = session.get(SqlHostedModelRequest, request_id)
    if entry is None:
        raise ValueError("model_request_not_found")
    run = session.get(SqlAgentRun, entry.run_id)
    assert run is not None
    _lock_scopes(session, user_id=run.requested_by_user_id, project_id=run.project_id)
    run = session.scalar(
        select(SqlAgentRun)
        .where(SqlAgentRun.id == run.id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    entry = session.scalar(
        select(SqlHostedModelRequest)
        .where(SqlHostedModelRequest.id == request_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    assert entry is not None and run is not None
    if entry.state != "PENDING":
        session.rollback()
        return
    spec = RuntimeSpec.model_validate(run.runtime_spec)
    source = UsageSource.PROVIDER_REPORTED if usage is not None else UsageSource.ESTIMATED
    if usage is not None:
        entry.input_tokens, entry.output_tokens = usage["input_tokens"], usage["output_tokens"]
        entry.cost_microusd = (
            entry.input_tokens * spec.input_microusd_per_million_tokens
            + entry.output_tokens * spec.output_microusd_per_million_tokens
            + 999_999
        ) // 1_000_000
    entry.state = "COMPLETED" if usage is not None else "UNCERTAIN"
    entry.settled_at = utc_now()
    event = _append_event_locked(
        session,
        run=run,
        idempotency_key=f"hosted-usage-{entry.id}",
        kind=AgentRunEventKind.USAGE_REPORTED,
        payload={
            "source": source.value,
            "input_tokens": entry.input_tokens,
            "output_tokens": entry.output_tokens,
            "total_tokens": entry.input_tokens + entry.output_tokens,
        },
        occurred_at=entry.settled_at,
    )
    session.add(
        SqlAgentRunUsage(
            run_id=run.id,
            event_cursor=event.cursor,
            source=source,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
            total_tokens=entry.input_tokens + entry.output_tokens,
            observed_at=entry.settled_at,
        )
    )
    increment_durable(session, "polycolab_hosted_settlement_total", outcome=entry.state)
    session.commit()


def recover_pending(session: Session) -> int:
    ids = list(
        session.scalars(
            select(SqlHostedModelRequest.id)
            .where(
                SqlHostedModelRequest.state == "PENDING",
                SqlHostedModelRequest.settle_by <= utc_now(),
            )
            .limit(100)
        )
    )
    session.rollback()
    for request_id in ids:
        settle(session, request_id, None)
    return len(ids)


@dataclass(frozen=True)
class Dispatch:
    request_id: UUID
    user_id: UUID
    profile_id: UUID
    base_url: str
    encrypted: EncryptedCredential
    payload: dict[str, object]
    spec: RuntimeSpec
    remaining: float


def prepare(
    request: Request,
    *,
    run_id: UUID,
    worker_id: str,
    generation: int,
    request_key: str,
    body: dict[str, object],
) -> Dispatch:
    with request.app.state.session_factory() as session:
        run = session.get(SqlAgentRun, run_id)
        if run is None:
            raise ProviderFailure("lease_lost")
        _lock_scopes(session, user_id=run.requested_by_user_id, project_id=run.project_id)
        run = session.scalar(
            select(SqlAgentRun)
            .where(SqlAgentRun.id == run_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        _require_live_lease(run, worker_id=worker_id, lease_generation=generation, now=utc_now())
        if run.status != AgentRunStatus.RUNNING or not project_policy.can(
            SqlAlchemyTransaction(session),
            run.project_id,
            run.requested_by_user_id,
            ProjectAction.RUN_AGENTS,
        ):
            raise ProviderFailure("authorization_revoked")
        spec = RuntimeSpec.model_validate(run.runtime_spec)
        payload = validated_request(
            body,
            model=run.gateway_model_id,
            max_output_tokens=spec.max_output_tokens,
            max_input_bytes=min(spec.max_input_bytes, spec.max_input_tokens),
        )
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = session.scalar(
            select(SqlHostedModelRequest).where(
                SqlHostedModelRequest.run_id == run_id,
                SqlHostedModelRequest.request_key == request_key,
            )
        )
        if existing is not None:
            raise ProviderFailure(
                "model_request_already_dispatched"
                if existing.request_digest == digest
                else "model_request_conflict"
            )
        count = (
            session.scalar(
                select(func.count())
                .select_from(SqlHostedModelRequest)
                .where(
                    SqlHostedModelRequest.run_id == run_id,
                    SqlHostedModelRequest.generation == generation,
                )
            )
            or 0
        )
        if count >= spec.max_model_requests:
            raise ProviderFailure("model_request_limit_exceeded")
        profile = session.get(SqlGatewayProfile, run.gateway_profile_id)
        if (
            profile is None
            or profile.deleted_at is not None
            or profile.user_id != run.requested_by_user_id
            or profile.credential_version != run.gateway_credential_version
            or profile.model_id != run.gateway_model_id
        ):
            raise ProviderFailure("gateway_profile_changed")
        if profile.wire_api != "responses":
            raise ProviderFailure("provider_protocol_incompatible")
        assert run.deadline_at is not None
        remaining = min(55, (utc(run.deadline_at) - utc_now()).total_seconds())
        if remaining <= 0:
            raise ProviderFailure("deadline_exceeded")
        entry = SqlHostedModelRequest(
            run_id=run_id,
            generation=generation,
            request_key=request_key,
            request_digest=digest,
            input_tokens=spec.max_input_tokens,
            output_tokens=spec.max_output_tokens,
            cost_microusd=spec.round_cost_microusd,
            settle_by=utc_now() + timedelta(seconds=remaining + 5),
        )
        encrypted = EncryptedCredential(
            profile.encrypted_credential, profile.wrapped_data_key, profile.encryption_key_version
        )
        user_id, profile_id, base_url = profile.user_id, profile.id, profile.base_url
        session.add(entry)
        session.commit()
        return Dispatch(
            entry.id, user_id, profile_id, base_url, encrypted, payload, spec, remaining
        )


def authorize_delivery(request: Request, run_id: UUID, worker_id: str, generation: int) -> None:
    with request.app.state.session_factory() as session:
        run = session.get(SqlAgentRun, run_id)
        _require_live_lease(run, worker_id=worker_id, lease_generation=generation, now=utc_now())
        profile = session.get(SqlGatewayProfile, run.gateway_profile_id)
        if (
            run.status != AgentRunStatus.RUNNING
            or profile is None
            or profile.deleted_at is not None
            or profile.credential_version != run.gateway_credential_version
            or not project_policy.can(
                SqlAlchemyTransaction(session),
                run.project_id,
                run.requested_by_user_id,
                ProjectAction.RUN_AGENTS,
            )
        ):
            raise ProviderFailure("authorization_revoked")


def settle_dispatch(request: Request, request_id: UUID, usage: dict[str, int] | None) -> None:
    with request.app.state.session_factory() as session:
        settle(session, request_id, usage)


async def respond(
    request: Request,
    *,
    run_id: UUID,
    worker_id: str,
    generation: int,
    request_key: str,
    body: dict[str, object],
) -> dict[str, str]:
    settings = request.app.state.settings
    dispatch = await run_in_threadpool(
        prepare,
        request,
        run_id=run_id,
        worker_id=worker_id,
        generation=generation,
        request_key=request_key,
        body=body,
    )
    request_id, spec = dispatch.request_id, dispatch.spec
    usage = None
    secret = ""
    try:
        async with asyncio.timeout(dispatch.remaining):
            secret = await run_in_threadpool(
                decrypt_credential,
                request.app.state.credential_wrapper,
                context=credential_context(
                    user_id=dispatch.user_id, profile_id=dispatch.profile_id
                ),
                encrypted=dispatch.encrypted,
            )
            await run_in_threadpool(authorize_delivery, request, run_id, worker_id, generation)
            transport = getattr(
                request.app.state, "hosted_provider_transport", async_transport.responses
            )
            data = await transport(
                base_url=dispatch.base_url,
                api_key=secret,
                payload=dispatch.payload,
                max_bytes=min(settings.gateway_max_response_bytes, 1_000_000),
            )
        data, usage = completed_response(
            [data], max_bytes=1_000_000, max_output_tokens=spec.max_output_tokens
        )
        if usage["input_tokens"] > spec.max_input_tokens:
            usage = None
            raise ProviderFailure("provider_usage_limit_exceeded")
    except IncompleteResponse as exc:
        if exc.usage["input_tokens"] <= spec.max_input_tokens:
            usage = exc.usage
        raise ProviderFailure(exc.code) from None
    except (ProviderFailure, ProviderTransportError) as exc:
        raise ProviderFailure(exc.code) from None
    except TimeoutError:
        raise ProviderFailure("provider_request_uncertain") from None
    except CredentialError:
        # No dispatch was possible; settle a zero-cost observation.
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        raise ProviderFailure("credential_decryption_failed") from None
    finally:
        secret = ""
        await run_in_threadpool(settle_dispatch, request, request_id, usage)
    await run_in_threadpool(authorize_delivery, request, run_id, worker_id, generation)
    return {"body": base64.b64encode(data).decode("ascii")}

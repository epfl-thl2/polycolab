"""Private worker-facing model gateway; never part of the browser API contract."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from polycolab.accounts.authentication import AuthenticationRequired, bearer_token
from polycolab.model_gateway.service import GrantInvalid, ProviderFailure, stream_model
from polycolab.model_gateway.stream import encode_error_sse
from polycolab.platform.observability import increment_durable


class ModelStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    model_id: str = Field(min_length=1, max_length=500)
    messages: list[dict[str, object]] = Field(min_length=1, max_length=128)
    max_output_tokens: int = Field(ge=1, le=100_000)


router = APIRouter(prefix="/internal/v1/model")


@router.post("/chat/completions", include_in_schema=False)
def stream_chat_completions(payload: ModelStreamRequest, request: Request) -> StreamingResponse:
    token = bearer_token(request.headers.get("authorization"))
    if token is None:
        raise AuthenticationRequired
    session = request.app.state.session_factory()
    try:
        stream = stream_model(
            session,
            wrapper=request.app.state.credential_wrapper,
            token=token,
            run_id=payload.run_id,
            model_id=payload.model_id,
            messages=payload.messages,
            max_output_tokens=payload.max_output_tokens,
            transport=request.app.state.provider_transport,
            limits=request.app.state.gateway_limits,
        )
        increment_durable(
            session,
            "polycolab_provider_requests_total",
            provider_class="configured_gateway",
            outcome="started",
        )
        session.commit()
    except GrantInvalid as exc:
        raise AuthenticationRequired from exc
    except ProviderFailure as exc:
        # Keep provider failures in the same normalized SSE contract, without
        # exposing provider details in an HTTP error body.
        stream = iter((encode_error_sse(exc.code), b"data: [DONE]\n\n"))
        increment_durable(
            session,
            "polycolab_provider_requests_total",
            provider_class="configured_gateway",
            outcome="provider_error",
        )
        session.commit()
    finally:
        session.close()
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )

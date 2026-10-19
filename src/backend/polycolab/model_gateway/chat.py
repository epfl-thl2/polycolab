"""Bounded text-only inference for direct chat; no tools or execution grants."""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.model_gateway.credentials import (
    CredentialError,
    EncryptedCredential,
    KeyWrapper,
    credential_context,
    decrypt_credential,
)
from polycolab.model_gateway.responses import completed_response
from polycolab.model_gateway.service import GatewayLimits, ProviderFailure, profile_for_user
from polycolab.model_gateway.stream import StreamLimits, normalize_model_stream
from polycolab.model_gateway.transport import ProviderTransport, ProviderTransportError


@dataclass(frozen=True)
class PlainChatRequest:
    base_url: str
    model_id: str
    responses: bool
    encrypted: EncryptedCredential
    context: bytes
    payload: dict[str, object]
    input_bytes: int
    reserved_tokens: int
    reserved_cost: int


@dataclass(frozen=True)
class PlainChatCompletion:
    text: str
    input_tokens: int
    output_tokens: int


def prepare_chat(
    session: Session,
    *,
    user_id: UUID,
    profile_id: UUID,
    messages: list[dict[str, object]],
    limits: GatewayLimits,
) -> PlainChatRequest:
    profile = profile_for_user(session, profile_id=profile_id, user_id=user_id)
    responses = profile.wire_api == "responses"
    payload: dict[str, object] = {"model": profile.model_id, "stream": True}
    if responses:
        payload.update(
            {"input": messages, "max_output_tokens": limits.max_output_tokens, "store": False}
        )
    else:
        payload.update(
            {
                "messages": messages,
                "max_tokens": limits.max_output_tokens,
                "stream_options": {"include_usage": True},
            }
        )
    input_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
    if input_bytes > limits.max_input_bytes:
        raise ProviderFailure("gateway_input_limit_exceeded")
    cost = (
        input_bytes * limits.input_microusd_per_million_tokens
        + limits.max_output_tokens * limits.output_microusd_per_million_tokens
        + 999_999
    ) // 1_000_000
    if cost > limits.max_cost_microusd:
        raise ProviderFailure("gateway_cost_limit_exceeded")
    return PlainChatRequest(
        base_url=profile.base_url,
        model_id=profile.model_id,
        responses=responses,
        encrypted=EncryptedCredential(
            profile.encrypted_credential, profile.wrapped_data_key, profile.encryption_key_version
        ),
        context=credential_context(user_id=user_id, profile_id=profile.id),
        payload=payload,
        input_bytes=input_bytes,
        reserved_tokens=input_bytes + limits.max_output_tokens,
        reserved_cost=cost,
    )


def complete_chat(
    request: PlainChatRequest,
    *,
    wrapper: KeyWrapper,
    transport: ProviderTransport,
    limits: GatewayLimits,
    timeout: float,
) -> PlainChatCompletion:
    try:
        credential = decrypt_credential(
            wrapper, context=request.context, encrypted=request.encrypted
        )
    except CredentialError:
        raise ProviderFailure("credential_unavailable") from None
    started = time.monotonic()
    try:
        response = transport.open_stream(
            base_url=request.base_url,
            api_key=credential,
            payload=request.payload,
            responses=request.responses,
        )
        try:

            def bounded_chunks() -> Iterator[bytes]:
                count = 0
                for chunk in response.chunks:
                    count += 1
                    if time.monotonic() - started > timeout:
                        raise ProviderFailure("provider_timeout")
                    if count > 4096:
                        raise ProviderFailure("provider_response_too_large")
                    yield chunk

            if request.responses:
                raw, usage = completed_response(
                    bounded_chunks(),
                    max_bytes=limits.max_response_bytes,
                    max_output_tokens=limits.max_output_tokens,
                )
                text: list[str] = []
                for event in raw.decode().replace("\r\n", "\n").split("\n\n"):
                    lines = [
                        line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")
                    ]
                    data = "\n".join(lines)
                    if not data or data == "[DONE]":
                        continue
                    frame = json.loads(data)
                    if frame.get("type") != "response.completed":
                        continue
                    for item in frame["response"].get("output", []):
                        if item.get("type") == "reasoning":
                            continue
                        if item.get("type") != "message" or item.get("role") != "assistant":
                            raise ProviderFailure("provider_tools_unsupported")
                        for part in item.get("content", []):
                            if part.get("type") == "output_text" and isinstance(
                                part.get("text"), str
                            ):
                                text.append(part["text"])
                            elif part.get("type") == "refusal" and isinstance(
                                part.get("refusal"), str
                            ):
                                text.append(part["refusal"])
                            else:
                                raise ProviderFailure("provider_invalid_response")
                result = PlainChatCompletion(
                    "".join(text), usage["input_tokens"], usage["output_tokens"]
                )
            else:
                pieces: list[str] = []
                prompt_tokens: int | None = None
                output_tokens: int | None = None
                for frame in normalize_model_stream(
                    bounded_chunks(),
                    max_output_tokens=limits.max_output_tokens,
                    limits=StreamLimits(max_response_bytes=limits.max_response_bytes),
                ):
                    if frame.tool_call_deltas or frame.finish_reason == "tool_calls":
                        raise ProviderFailure("provider_tools_unsupported")
                    if frame.finish_reason == "length":
                        raise ProviderFailure("provider_response_incomplete")
                    if frame.content:
                        pieces.append(frame.content)
                    if frame.usage:
                        prompt_tokens = frame.usage.prompt_tokens
                        output_tokens = frame.usage.completion_tokens
                if prompt_tokens is None or output_tokens is None:
                    raise ProviderFailure("provider_usage_required")
                result = PlainChatCompletion("".join(pieces), prompt_tokens, output_tokens)
            if not result.text.strip():
                raise ProviderFailure("model_empty_completion")
            return result
        except ValueError, KeyError, TypeError, AttributeError:
            raise ProviderFailure("provider_invalid_response") from None
        finally:
            response.close()
    except ProviderTransportError as exc:
        raise ProviderFailure(exc.code) from None
    finally:
        credential = ""

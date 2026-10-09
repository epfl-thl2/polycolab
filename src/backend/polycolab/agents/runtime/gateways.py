"""Database-free HTTP clients used by the private agent worker."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Protocol, cast

import httpx

from polycolab.agents.runtime.contracts import (
    FinishReason,
    ModelStreamFrame,
    ModelTurn,
    ToolCallDelta,
    Usage,
)


class ModelGatewayError(Exception):
    """A stable private-gateway failure code with no provider-controlled detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ToolGatewayError(Exception):
    """Stable private-tool failure without response details."""

    def __init__(self, code: str = "tool_gateway_failed") -> None:
        super().__init__(code)
        self.code = code


class ToolGateway(Protocol):
    def call(
        self,
        *,
        capability: str,
        name: str,
        arguments: dict[str, object],
        invocation: str,
        source_event_cursor: int | None,
    ) -> dict[str, object]: ...


class HttpToolGateway:
    """Private tool client. The capability exists only in its bearer header."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("private tool gateway URL and positive timeout are required")
        self._url = base_url.rstrip("/") + "/internal/v1/tools/call"
        self._timeout_seconds = timeout_seconds

    def call(
        self,
        *,
        capability: str,
        name: str,
        arguments: dict[str, object],
        invocation: str,
        source_event_cursor: int | None,
    ) -> dict[str, object]:
        try:
            response = httpx.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {capability}",
                    "X-Polycolab-Tool-Invocation": invocation,
                    **(
                        {"X-Polycolab-Source-Event-Cursor": str(source_event_cursor)}
                        if source_event_cursor is not None
                        else {}
                    ),
                },
                json={"name": name, "arguments": arguments},
                timeout=self._timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ToolGatewayError("tool_gateway_unavailable") from exc
        if response.status_code in {401, 403}:
            raise ToolGatewayError("tool_authorization_denied")
        if response.status_code != 200:
            raise ToolGatewayError("tool_gateway_failed")
        try:
            value = response.json()
        except ValueError as exc:
            raise ToolGatewayError("tool_gateway_invalid") from exc
        if not isinstance(value, dict):
            raise ToolGatewayError("tool_gateway_invalid")
        return cast(dict[str, object], value)


class HttpModelGateway:
    """Worker-side client for Polycolab's private normalized model SSE endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        max_response_bytes: int = 1_000_000,
        max_line_bytes: int = 65_536,
        max_content_bytes: int = 1_000_000,
    ) -> None:
        if not base_url or timeout_seconds <= 0:
            raise ValueError("private gateway URL and positive timeout are required")
        if min(max_response_bytes, max_line_bytes, max_content_bytes) < 1:
            raise ValueError("private gateway stream limits must be positive")
        self._url = base_url.rstrip("/") + "/internal/v1/model/chat/completions"
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_line_bytes = max_line_bytes
        self._max_content_bytes = max_content_bytes

    def stream(self, turn: ModelTurn, *, grant: str) -> Iterator[ModelStreamFrame]:
        payload = {
            "run_id": str(turn.run_id),
            "model_id": turn.model_id,
            "messages": turn.messages,
            "max_output_tokens": turn.max_output_tokens,
        }

        def frames() -> Iterator[ModelStreamFrame]:
            try:
                with httpx.Client(
                    timeout=self._timeout_seconds,
                    trust_env=False,
                    follow_redirects=False,
                ) as client:
                    with client.stream(
                        "POST",
                        self._url,
                        headers={"Authorization": f"Bearer {grant}"},
                        json=payload,
                    ) as response:
                        if response.status_code != 200:
                            raise ModelGatewayError("model_gateway_unavailable")
                        content_length = response.headers.get("content-length")
                        if content_length is not None:
                            try:
                                if int(content_length) > self._max_response_bytes:
                                    raise ModelGatewayError("model_gateway_response_too_large")
                            except ValueError as exc:
                                raise ModelGatewayError("model_gateway_stream_invalid") from exc
                        saw_done = False
                        response_bytes = 0
                        content_bytes = 0
                        for line in response.iter_lines():
                            encoded_line = line.encode("utf-8")
                            response_bytes += len(encoded_line) + 1
                            if response_bytes > self._max_response_bytes:
                                raise ModelGatewayError("model_gateway_response_too_large")
                            if len(encoded_line) > self._max_line_bytes:
                                raise ModelGatewayError("model_gateway_stream_too_large")
                            if not line or line.startswith(":"):
                                continue
                            if not line.startswith("data: "):
                                raise ModelGatewayError("model_gateway_stream_invalid")
                            encoded = line[6:]
                            if encoded == "[DONE]":
                                saw_done = True
                                break
                            frame = _decode_gateway_frame(
                                encoded, max_output_tokens=turn.max_output_tokens
                            )
                            if frame.content is not None:
                                content_bytes += len(frame.content.encode("utf-8"))
                                if content_bytes > self._max_content_bytes:
                                    raise ModelGatewayError("model_gateway_output_too_large")
                            yield frame
                        if not saw_done:
                            raise ModelGatewayError("model_gateway_stream_incomplete")
            except ModelGatewayError:
                raise
            except httpx.HTTPError as exc:
                raise ModelGatewayError("model_gateway_unavailable") from exc

        return frames()


_GATEWAY_ERROR_CODES = frozenset(
    {
        "credential_unavailable",
        "gateway_cost_limit_exceeded",
        "gateway_input_limit_exceeded",
        "gateway_output_limit_exceeded",
        "gateway_request_invalid",
        "provider_output_limit_exceeded",
        "provider_rejected",
        "provider_response_too_large",
        "provider_stream_incomplete",
        "provider_stream_invalid",
        "provider_stream_limit_exceeded",
        "provider_tools_unsupported",
        "provider_unavailable",
    }
)


def _decode_gateway_frame(encoded: str, *, max_output_tokens: int) -> ModelStreamFrame:
    """Parse the gateway's small allowlisted frame, never a provider frame."""

    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ModelGatewayError("model_gateway_stream_invalid") from exc
    if not isinstance(value, dict):
        raise ModelGatewayError("model_gateway_stream_invalid")
    error = value.get("error")
    if error is not None:
        if not isinstance(error, dict) or not isinstance(error.get("code"), str):
            raise ModelGatewayError("model_gateway_stream_invalid")
        code = cast(str, error["code"])
        raise ModelGatewayError(code if code in _GATEWAY_ERROR_CODES else "model_gateway_failed")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ModelGatewayError("model_gateway_stream_invalid")
    choice = choices[0]
    delta = choice.get("delta")
    if not isinstance(delta, dict):
        raise ModelGatewayError("model_gateway_stream_invalid")
    content = delta.get("content")
    if content is not None and not isinstance(content, str):
        raise ModelGatewayError("model_gateway_stream_invalid")
    raw_calls = delta.get("tool_calls")
    calls: tuple[ToolCallDelta, ...] = ()
    if raw_calls is not None:
        if not isinstance(raw_calls, list) or len(raw_calls) > 16:
            raise ModelGatewayError("model_gateway_stream_invalid")
        parsed: list[ToolCallDelta] = []
        for raw_call in raw_calls:
            if not isinstance(raw_call, dict):
                raise ModelGatewayError("model_gateway_stream_invalid")
            index = raw_call.get("index")
            function = raw_call.get("function", {})
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= 16
                or not isinstance(function, dict)
            ):
                raise ModelGatewayError("model_gateway_stream_invalid")
            name = function.get("name")
            arguments = function.get("arguments")
            if name is not None and (not isinstance(name, str) or len(name) > 64):
                raise ModelGatewayError("model_gateway_stream_invalid")
            if arguments is not None and not isinstance(arguments, str):
                raise ModelGatewayError("model_gateway_stream_invalid")
            parsed.append(ToolCallDelta(index=index, name=name, arguments=arguments))
        calls = tuple(parsed)
    finish_reason = choice.get("finish_reason")
    if finish_reason is not None and finish_reason not in {"stop", "length", "tool_calls"}:
        raise ModelGatewayError("model_gateway_stream_invalid")
    usage_value = value.get("usage")
    usage = None
    if usage_value is not None:
        if not isinstance(usage_value, dict):
            raise ModelGatewayError("model_gateway_stream_invalid")
        completion = usage_value.get("completion_tokens")
        prompt = usage_value.get("prompt_tokens")
        total = usage_value.get("total_tokens")
        values = (completion, prompt, total)
        if (
            any(
                item is not None
                and (isinstance(item, bool) or not isinstance(item, int) or item < 0)
                for item in values
            )
            or completion is None
            or completion > max_output_tokens
        ):
            raise ModelGatewayError("model_gateway_stream_invalid")
        usage = Usage(
            completion_tokens=cast(int, completion),
            prompt_tokens=cast(int | None, prompt),
            total_tokens=cast(int | None, total),
        )
    return ModelStreamFrame(
        content=content,
        finish_reason=cast(FinishReason | None, finish_reason),
        usage=usage,
        tool_call_deltas=calls,
    )

"""Strict, bounded parsing and normalization for provider SSE responses."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, cast

from polycolab.agents.runtime.contracts import FinishReason, ModelStreamFrame, ToolCallDelta, Usage
from polycolab.model_gateway.transport import ProviderTransportError


@dataclass(frozen=True)
class StreamLimits:
    max_response_bytes: int
    max_chunks: int = 1024
    max_line_bytes: int = 65_536
    max_event_bytes: int = 262_144
    max_content_bytes: int = 1_000_000
    max_tool_call_bytes: int = 65_536
    max_tool_calls: int = 16


def _failure(code: str) -> ProviderTransportError:
    return ProviderTransportError(code)


def iter_sse_objects(chunks: Iterable[bytes], limits: StreamLimits) -> Iterator[dict[str, Any]]:
    """Parse only the SSE subset required by the built-in runtime.

    Provider bytes are never returned in errors.  The parser requires a DONE
    marker, so a truncated connection cannot be mistaken for a completed turn.
    """

    pending = bytearray()
    data_lines: list[bytes] = []
    response_bytes = 0
    event_bytes = 0
    chunk_count = 0
    done = False

    def dispatch() -> dict[str, Any] | None:
        nonlocal data_lines, event_bytes, chunk_count, done
        if not data_lines:
            event_bytes = 0
            return None
        raw = b"\n".join(data_lines)
        data_lines = []
        event_bytes = 0
        if raw == b"[DONE]":
            done = True
            return None
        try:
            decoded = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _failure("provider_stream_invalid") from exc
        if not isinstance(decoded, dict):
            raise _failure("provider_stream_invalid")
        chunk_count += 1
        if chunk_count > limits.max_chunks:
            raise _failure("provider_stream_limit_exceeded")
        return decoded

    def consume_line(raw_line: bytes) -> Iterator[dict[str, Any]]:
        nonlocal event_bytes
        line = raw_line[:-1] if raw_line.endswith(b"\r") else raw_line
        if len(line) > limits.max_line_bytes:
            raise _failure("provider_stream_limit_exceeded")
        if not line:
            item = dispatch()
            if item is not None:
                yield item
            return
        if line.startswith(b":"):
            return
        if not line.startswith(b"data: "):
            raise _failure("provider_stream_invalid")
        data = line[6:]
        event_bytes += len(data)
        if event_bytes > limits.max_event_bytes:
            raise _failure("provider_stream_limit_exceeded")
        data_lines.append(data)

    for chunk in chunks:
        response_bytes += len(chunk)
        if response_bytes > limits.max_response_bytes:
            raise _failure("provider_response_too_large")
        pending.extend(chunk)
        while True:
            newline = pending.find(b"\n")
            if newline < 0:
                if len(pending) > limits.max_line_bytes:
                    raise _failure("provider_stream_limit_exceeded")
                break
            line = bytes(pending[:newline])
            del pending[: newline + 1]
            yield from consume_line(line)
            if done:
                return
    if pending:
        raise _failure("provider_stream_incomplete")
    if data_lines:
        raise _failure("provider_stream_incomplete")
    if not done:
        raise _failure("provider_stream_incomplete")


def normalize_model_stream(
    chunks: Iterable[bytes], *, max_output_tokens: int, limits: StreamLimits
) -> Iterator[ModelStreamFrame]:
    """Convert provider objects to a small, validated model-frame contract."""

    completion_usage: Usage | None = None
    terminal_reason: str | None = None
    content_bytes = 0
    tool_bytes = 0
    for raw in iter_sse_objects(chunks, limits):
        if "error" in raw:
            raise _failure("provider_rejected")
        usage_raw = raw.get("usage")
        usage: Usage | None = None
        if usage_raw is not None:
            if not isinstance(usage_raw, dict):
                raise _failure("provider_usage_invalid")
            completion = usage_raw.get("completion_tokens")
            prompt = usage_raw.get("prompt_tokens")
            total = usage_raw.get("total_tokens")
            if (
                isinstance(completion, bool)
                or not isinstance(completion, int)
                or completion < 0
                or completion > max_output_tokens
            ):
                raise _failure("provider_output_limit_exceeded")
            values = (prompt, total)
            if any(
                value is not None
                and (isinstance(value, bool) or not isinstance(value, int) or value < 0)
                for value in values
            ):
                raise _failure("provider_usage_invalid")
            usage = Usage(completion, prompt, total)
            completion_usage = usage
        choices = raw.get("choices", [])
        if not isinstance(choices, list) or len(choices) > 1:
            raise _failure("provider_stream_invalid")
        content: str | None = None
        tool_call_deltas: tuple[ToolCallDelta, ...] = ()
        finish_reason: FinishReason | None = None
        if choices:
            choice = choices[0]
            if not isinstance(choice, dict):
                raise _failure("provider_stream_invalid")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                raise _failure("provider_stream_invalid")
            raw_tool_calls = delta.get("tool_calls")
            if raw_tool_calls is not None:
                if (
                    not isinstance(raw_tool_calls, list)
                    or len(raw_tool_calls) > limits.max_tool_calls
                ):
                    raise _failure("provider_stream_invalid")
                parsed_calls: list[ToolCallDelta] = []
                for raw_call in raw_tool_calls:
                    if not isinstance(raw_call, dict):
                        raise _failure("provider_stream_invalid")
                    index = raw_call.get("index")
                    function = raw_call.get("function", {})
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or index < 0
                        or index >= limits.max_tool_calls
                        or not isinstance(function, dict)
                    ):
                        raise _failure("provider_stream_invalid")
                    name = function.get("name")
                    arguments = function.get("arguments")
                    if name is not None and (not isinstance(name, str) or len(name) > 64):
                        raise _failure("provider_stream_invalid")
                    if arguments is not None:
                        if not isinstance(arguments, str):
                            raise _failure("provider_stream_invalid")
                        tool_bytes += len(arguments.encode("utf-8"))
                        if tool_bytes > limits.max_tool_call_bytes:
                            raise _failure("provider_stream_limit_exceeded")
                    # Provider call IDs are intentionally dropped at this boundary.
                    parsed_calls.append(ToolCallDelta(index=index, name=name, arguments=arguments))
                tool_call_deltas = tuple(parsed_calls)
            raw_content = delta.get("content")
            if raw_content is not None:
                if not isinstance(raw_content, str):
                    raise _failure("provider_stream_invalid")
                content_bytes += len(raw_content.encode("utf-8"))
                if content_bytes > limits.max_content_bytes:
                    raise _failure("provider_output_limit_exceeded")
                content = raw_content
            raw_reason = choice.get("finish_reason")
            if raw_reason is not None:
                if raw_reason not in {"stop", "length", "tool_calls"}:
                    raise _failure("provider_finish_reason_unsupported")
                finish_reason = cast(FinishReason, raw_reason)
                terminal_reason = raw_reason
        yield ModelStreamFrame(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            tool_call_deltas=tool_call_deltas,
        )
    if completion_usage is None:
        raise _failure("provider_usage_required")
    if terminal_reason is None:
        raise _failure("provider_finish_reason_required")


def encode_sse(frame: ModelStreamFrame) -> bytes:
    """Encode only normalized fields for the private worker-facing stream."""

    choice: dict[str, object] = {"delta": {}}
    if frame.content is not None:
        choice["delta"] = {"content": frame.content}
    if frame.finish_reason is not None:
        choice["finish_reason"] = frame.finish_reason
    if frame.tool_call_deltas:
        choice["delta"] = {
            "tool_calls": [
                {
                    "index": call.index,
                    "function": {
                        **({"name": call.name} if call.name is not None else {}),
                        **({"arguments": call.arguments} if call.arguments is not None else {}),
                    },
                }
                for call in frame.tool_call_deltas
            ]
        }
    payload: dict[str, object] = {"choices": [choice]}
    if frame.usage is not None:
        payload["usage"] = {
            "completion_tokens": frame.usage.completion_tokens,
            **(
                {"prompt_tokens": frame.usage.prompt_tokens}
                if frame.usage.prompt_tokens is not None
                else {}
            ),
            **(
                {"total_tokens": frame.usage.total_tokens}
                if frame.usage.total_tokens is not None
                else {}
            ),
        }
    return b"data: " + json.dumps(payload, separators=(",", ":")).encode() + b"\n\n"


def encode_error_sse(code: str) -> bytes:
    """Encode a stable gateway failure without provider-controlled details."""

    payload = json.dumps({"error": {"code": code}}, separators=(",", ":"))
    return b"data: " + payload.encode() + b"\n\n"

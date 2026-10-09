"""Bounded Responses transport for hosted Codex, with provider-owned usage.

Only streaming, stateless generation is supported. No URL forwarding, remote
tools, background requests, stored responses, or automatic retries.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from polycolab.model_gateway.service import ProviderFailure

ALLOWED_FIELDS = frozenset(
    {
        "model",
        "input",
        "instructions",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "reasoning",
        "text",
        "stream",
        "store",
        "include",
        "max_output_tokens",
        "prompt_cache_key",
        "truncation",
        "service_tier",
    }
)
LOCAL_TOOL_TYPES = frozenset({"function", "custom", "local_shell"})


def validated_request(
    body: dict[str, Any], *, model: str, max_output_tokens: int, max_input_bytes: int
) -> dict[str, Any]:
    if (
        set(body) - ALLOWED_FIELDS
        or body.get("model") != model
        or body.get("stream") is not True
        or body.get("store", False) is not False
    ):
        raise ProviderFailure("gateway_request_invalid")
    tools = body.get("tools", [])
    if not isinstance(tools, list) or len(tools) > 64:
        raise ProviderFailure("gateway_request_invalid")
    for tool in tools:
        if (
            not isinstance(tool, dict)
            or not isinstance(tool.get("type"), str)
            or tool["type"] not in LOCAL_TOOL_TYPES
        ):
            raise ProviderFailure("provider_tools_unsupported")

    # Do not let input references trigger provider-side URL fetches or retrieval
    # of another run's stored objects. Codex sends complete stateless text input.
    def inspect(value: object, depth: int = 0) -> None:
        if depth > 32:
            raise ProviderFailure("gateway_request_invalid")
        if isinstance(value, dict):
            if any(key in value for key in ("image_url", "file_url", "file_id")):
                raise ProviderFailure("gateway_request_invalid")
            if isinstance(value.get("type"), str) and value["type"] in {
                "item_reference",
                "input_image",
                "input_file",
            }:
                raise ProviderFailure("gateway_request_invalid")
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                inspect(child, depth + 1)

    inspect(body.get("input"))
    result = {**body, "store": False, "max_output_tokens": max_output_tokens}
    if len(json.dumps(result, ensure_ascii=False).encode()) > max_input_bytes:
        raise ProviderFailure("gateway_input_limit_exceeded")
    return result


class IncompleteResponse(ProviderFailure):
    """A non-deliverable terminal response with validated billable usage."""

    def __init__(self, usage: dict[str, int]) -> None:
        super().__init__("provider_response_incomplete")
        self.usage = usage


def completed_response(
    chunks: Iterable[bytes], *, max_bytes: int, max_output_tokens: int
) -> tuple[bytes, dict[str, int]]:
    """Buffer a bounded response; release only after validated terminal usage.

    The guest sees provider-native frames, but never raw provider failures. The
    browser still receives separately committed normalized Codex events.
    """
    data = bytearray()
    for chunk in chunks:
        if len(data) + len(chunk) > max_bytes:
            raise ProviderFailure("provider_response_too_large")
        data.extend(chunk)
    try:
        text = data.decode("utf-8").replace("\r\n", "\n")
        terminal: dict[str, int] | None = None
        event_count = 0
        incomplete = False
        for event in text.split("\n\n"):
            lines = [line[5:].lstrip() for line in event.splitlines() if line.startswith("data:")]
            if not lines:
                continue
            raw = "\n".join(lines)
            if raw == "[DONE]":
                continue
            event_count += 1
            if event_count > 4096 or len(raw.encode()) > max_bytes:
                raise ValueError
            frame = json.loads(raw)
            if not isinstance(frame, dict) or terminal is not None:
                raise ValueError
            if frame.get("type") in {"error", "response.failed"}:
                raise ProviderFailure("provider_rejected")
            if frame.get("type") in {"response.completed", "response.incomplete"}:
                incomplete = frame["type"] == "response.incomplete"
                response = frame["response"]
                if response.get("status") != ("incomplete" if incomplete else "completed"):
                    raise ValueError
                usage = response["usage"]
                keys = ("input_tokens", "output_tokens", "total_tokens")
                if any(type(usage.get(key)) is not int or usage[key] < 0 for key in keys):
                    raise ValueError
                if (
                    usage["output_tokens"] > max_output_tokens
                    or usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]
                ):
                    raise ValueError
                terminal = {key: usage[key] for key in keys}
        if terminal is None or not text.endswith("\n\n"):
            raise ValueError
        if incomplete:
            raise IncompleteResponse(terminal)
        return bytes(data), terminal
    except ValueError, UnicodeError, KeyError, TypeError, AttributeError:
        raise ProviderFailure("provider_stream_invalid") from None

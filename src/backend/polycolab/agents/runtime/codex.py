"""Codex app-server adapter. The guest is untrusted; policy lives in the API.

Only assistant text and normalized tool summaries become durable events. Codex
thread IDs, reasoning, commands, file contents and token claims are not history.
The protocol is pinned to Codex CLI 0.154.0, including dynamic tools.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

CODEX_VERSION = "0.154.0"
MAX_FRAME_BYTES = 1_000_000


class CodexFailure(Exception):
    """Stable codes only; never include guest-controlled error details."""


class CodexChannel(Protocol):
    async def send(self, message: dict[str, object]) -> None: ...

    async def receive(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class CodexTask:
    model: str
    messages: list[dict[str, object]]
    tools: list[dict[str, Any]]
    max_tool_calls: int = 16
    max_argument_bytes: int = 65_536
    max_result_bytes: int = 262_144
    max_text_bytes: int = 200_000
    max_events: int = 4096


EventWriter = Callable[[str, str, dict[str, object]], Awaitable[int]]
ToolExecutor = Callable[[str, dict[str, object], str, int], Awaitable[dict[str, object]]]


def decode_frame(data: bytes) -> dict[str, object]:
    if len(data) > MAX_FRAME_BYTES:
        raise CodexFailure("codex_frame_too_large")
    try:
        result = json.loads(data)
    except ValueError, UnicodeError, RecursionError:
        raise CodexFailure("codex_protocol_invalid") from None
    if not isinstance(result, dict):
        raise CodexFailure("codex_protocol_invalid")
    return result


class CodexSession:
    def __init__(
        self, channel: CodexChannel, task: CodexTask, event: EventWriter, tool: ToolExecutor
    ) -> None:
        self.channel, self.task, self.event, self.tool = channel, task, event, tool
        self.pending: deque[dict[str, object]] = deque()
        self.calls = 0
        self.events = 0
        self.text: list[str] = []
        self.text_bytes = 0
        self.thread_id: str | None = None
        self.turn_id: str | None = None
        self.seen_calls: set[str] = set()
        self.local_tools: dict[str, tuple[str, int]] = {}

    async def _receive(self, *, pending: bool = True) -> dict[str, object]:
        if pending and self.pending:
            return self.pending.popleft()
        self.events += 1
        if self.events > self.task.max_events:
            raise CodexFailure("codex_event_limit_exceeded")
        return await self.channel.receive()

    async def _request(
        self, request_id: int, method: str, params: dict[str, object]
    ) -> dict[str, Any]:
        await self.channel.send({"id": request_id, "method": method, "params": params})
        while True:
            message = await self._receive(pending=False)
            if message.get("id") == request_id and "method" not in message:
                result = message.get("result")
                if "error" in message or not isinstance(result, dict):
                    raise CodexFailure("codex_request_failed")
                return result
            # Start notifications may precede their RPC response. Bind the
            # returned thread/turn identity before processing any guest action.
            self.pending.append(message)

    async def run(self) -> str:
        await self._request(
            1,
            "initialize",
            {
                "clientInfo": {"name": "polycolab", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await self.channel.send({"method": "initialized"})
        instructions = "\n\n".join(
            str(message["content"])
            for message in self.task.messages
            if message.get("role") == "system"
        )
        transcript = json.dumps(
            [message for message in self.task.messages if message.get("role") != "system"],
            ensure_ascii=False,
        )
        dynamic_tools = [
            {
                "name": definition["function"]["name"],
                "description": definition["function"]["description"],
                "inputSchema": definition["function"]["parameters"],
            }
            for definition in self.task.tools
        ]
        result = await self._request(
            2,
            "thread/start",
            {
                "model": self.task.model,
                "modelProvider": "polycolab",
                "cwd": "/workspace",
                "approvalPolicy": "never",
                # Only inside the independently isolated VM. No host process uses this policy.
                "sandbox": "danger-full-access",
                "baseInstructions": instructions,
                "ephemeral": True,
                "dynamicTools": dynamic_tools,
            },
        )
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise CodexFailure("codex_protocol_invalid")
        self.thread_id = thread["id"]
        result = await self._request(
            3,
            "turn/start",
            {
                "threadId": self.thread_id,
                "input": [{"type": "text", "text": transcript}],
            },
        )
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise CodexFailure("codex_protocol_invalid")
        self.turn_id = turn["id"]
        while True:
            message = await self._receive()
            if await self._notification(message):
                if not self.text:
                    raise CodexFailure("model_empty_completion")
                return "".join(self.text)

    async def _notification(self, message: dict[str, object]) -> bool:
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            raise CodexFailure("codex_protocol_invalid")
        if self.thread_id is not None and params.get("threadId", self.thread_id) != self.thread_id:
            raise CodexFailure("codex_thread_mismatch")
        if self.turn_id is not None and params.get("turnId", self.turn_id) != self.turn_id:
            raise CodexFailure("codex_turn_mismatch")
        if method == "item/tool/call":
            await self._dynamic_tool(message, params)
        elif "id" in message and method is not None:
            # Never approve an unexpected request (including user input or escalation).
            await self.channel.send(
                {
                    "id": message["id"],
                    "error": {
                        "code": -32601,
                        "message": "unsupported request",
                    },
                }
            )
            raise CodexFailure("codex_request_unsupported")
        elif method == "item/agentMessage/delta":
            delta = params.get("delta")
            if not isinstance(delta, str):
                raise CodexFailure("codex_protocol_invalid")
            self.text_bytes += len(delta.encode())
            if self.text_bytes > self.task.max_text_bytes:
                raise CodexFailure("codex_text_limit_exceeded")
            await self.event(f"text-{self.events}", "ASSISTANT_DELTA", {"text": delta})
            self.text.append(delta)
        elif method in {"item/started", "item/completed"}:
            await self._local_tool(method, params)
        elif method == "turn/completed":
            turn = params.get("turn")
            if not isinstance(turn, dict) or turn.get("status") != "completed":
                raise CodexFailure("codex_turn_failed")
            if self.turn_id is None or turn.get("id") != self.turn_id:
                raise CodexFailure("codex_turn_mismatch")
            return True
        elif method == "error":
            raise CodexFailure("codex_turn_failed")
        # Reasoning, usage claims, raw output and unknown notifications are discarded.
        return False

    async def _dynamic_tool(self, message: dict[str, Any], params: dict[str, Any]) -> None:
        name, arguments, call_id = params.get("tool"), params.get("arguments"), params.get("callId")
        allowed = {definition["function"]["name"] for definition in self.task.tools}
        if (
            not isinstance(name, str)
            or name not in allowed
            or not isinstance(arguments, dict)
            or not isinstance(call_id, str)
            or call_id in self.seen_calls
            or "id" not in message
        ):
            raise CodexFailure("codex_tool_invalid")
        if len(json.dumps(arguments).encode()) > self.task.max_argument_bytes:
            raise CodexFailure("tool_argument_limit_exceeded")
        self.seen_calls.add(call_id)
        self.calls += 1
        if self.calls > self.task.max_tool_calls:
            raise CodexFailure("tool_call_limit_exceeded")
        # Never use guest-controlled IDs for authorization, replay or provenance.
        invocation = f"tool-{self.calls}"
        cursor = await self.event(
            invocation + "-requested",
            "TOOL_REQUESTED",
            {
                "tool_name": name,
                "round": self.calls,
            },
        )
        result = await self.tool(name, arguments, invocation, cursor)
        encoded = json.dumps(result, separators=(",", ":"))
        if len(encoded.encode()) > self.task.max_result_bytes:
            raise CodexFailure("tool_result_limit_exceeded")
        await self.event(
            invocation + "-result",
            "TOOL_RESULT",
            {
                "tool_name": name,
                "round": self.calls,
                "outcome": "error" if "error" in result else "ok",
            },
        )
        await self.channel.send(
            {
                "id": message["id"],
                "result": {
                    "contentItems": [{"type": "inputText", "text": encoded}],
                    "success": "error" not in result,
                },
            }
        )

    async def _local_tool(self, method: str, params: dict[str, Any]) -> None:
        item = params.get("item")
        if not isinstance(item, dict):
            return
        name = {"commandExecution": "shell", "fileChange": "files"}.get(str(item.get("type")))
        item_id = item.get("id")
        if name is None or not isinstance(item_id, str):
            return
        if method == "item/started":
            if item_id in self.local_tools:
                raise CodexFailure("codex_tool_invalid")
            self.calls += 1
            if self.calls > self.task.max_tool_calls:
                raise CodexFailure("tool_call_limit_exceeded")
            self.local_tools[item_id] = (name, self.calls)
            await self.event(
                f"local-{self.calls}-requested",
                "TOOL_REQUESTED",
                {
                    "tool_name": name,
                    "round": self.calls,
                },
            )
        elif item_id in self.local_tools:
            _, ordinal = self.local_tools.pop(item_id)
            await self.event(
                f"local-{ordinal}-result",
                "TOOL_RESULT",
                {
                    "tool_name": name,
                    "round": ordinal,
                    "outcome": "ok" if item.get("status") == "completed" else "failed",
                },
            )

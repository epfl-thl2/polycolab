"""Test-only core with a deterministic Responses transport and real persistence."""

from __future__ import annotations

import json
from typing import Any

from polycolab.app.application import create_app
from polycolab.model_gateway.transport import ProviderStreamResponse
from polycolab.platform.config import Settings

ANSWER = "Native gVisor research completed."


def response(*, tool_call: tuple[str, str, dict[str, Any]] | None = None) -> bytes:
    item = {
        "id": "msg_native",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": ANSWER, "annotations": []}],
    }
    completed = {
        "id": "resp_native",
        "object": "response",
        "status": "completed",
        "output": [item],
        "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
    }
    events: list[dict[str, Any]] = [
        {
            "type": "response.created",
            "response": {**completed, "status": "in_progress", "output": []},
        },
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {**item, "status": "in_progress", "content": []},
        },
        {
            "type": "response.content_part.added",
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": "", "annotations": []},
        },
        {
            "type": "response.output_text.delta",
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "delta": ANSWER,
        },
        {
            "type": "response.output_text.done",
            "item_id": item["id"],
            "output_index": 0,
            "content_index": 0,
            "text": ANSWER,
        },
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": completed},
    ]
    if tool_call is not None:
        call_id, name, arguments = tool_call
        encoded = json.dumps(arguments)
        call = {
            "id": "fc_" + call_id,
            "type": "function_call",
            "name": name,
            "arguments": encoded,
            "call_id": call_id,
            "status": "completed",
        }
        events = [
            {
                "type": "response.created",
                "response": {**completed, "status": "in_progress", "output": []},
            },
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {**call, "arguments": "", "status": "in_progress"},
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": call["id"],
                "output_index": 0,
                "delta": encoded,
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": call["id"],
                "output_index": 0,
                "arguments": encoded,
            },
            {"type": "response.output_item.done", "output_index": 0, "item": call},
            {"type": "response.completed", "response": {**completed, "output": [call]}},
        ]
    return b"".join(
        (
            "event: "
            + event["type"]
            + "\ndata: "
            + json.dumps({**event, "sequence_number": i})
            + "\n\n"
        ).encode()
        for i, event in enumerate(events)
    )


class ValidationProvider:
    def open_stream(self, **_: Any) -> ProviderStreamResponse:
        return ProviderStreamResponse(200, iter([response()]), lambda: None)


async def respond(*, payload: dict[str, Any], **_: Any) -> bytes:
    names = {tool.get("name") for tool in payload["tools"]}
    assert {"get_context", "exec_command", "export_artifact"} <= names
    results = {
        item.get("call_id")
        for item in payload["input"]
        if item.get("type") == "function_call_output"
    }
    if "call_context" not in results:
        return response(tool_call=("call_context", "get_context", {}))
    if "call_shell" not in results:
        return response(
            tool_call=(
                "call_shell",
                "exec_command",
                {
                    "cmd": "printf 'native result\\n' > /outputs/result.txt && "
                    "printf 'Native project edit\\n' > /workspace/native.txt",
                    "yield_time_ms": 1000,
                    "max_output_tokens": 1000,
                },
            )
        )
    if "call_export" not in results:
        return response(
            tool_call=(
                "call_export",
                "export_artifact",
                {
                    "path": "result.txt",
                    "display_name": "Native result.txt",
                    "media_type": "text/plain",
                },
            )
        )
    return response()


app = create_app(Settings())
app.state.provider_transport = ValidationProvider()
app.state.hosted_provider_transport = respond

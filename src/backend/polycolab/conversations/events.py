"""Semantic transcript projection of committed, sanitized execution events."""

from polycolab.entities.conversation import (
    ErrorData,
    ToolCallData,
    ToolResultData,
    safe_failure_code,
)
from polycolab.entities.enums import AgentRunEventKind


def semantic_payload(
    kind: AgentRunEventKind, payload: dict[str, object]
) -> ToolCallData | ToolResultData | ErrorData | None:
    if kind in {AgentRunEventKind.TOOL_REQUESTED, AgentRunEventKind.TOOL_RESULT}:
        name = payload.get("tool_name")
        if not isinstance(name, str) or not name:
            raise ValueError("tool event requires a name")
        if kind is AgentRunEventKind.TOOL_REQUESTED:
            return ToolCallData(call_id=None, name=name)
        outcome = payload.get("outcome", "unknown")
        if not isinstance(outcome, str):
            raise ValueError("tool event requires an outcome")
        return ToolResultData(call_id=None, name=name, outcome=outcome)
    if kind in {
        AgentRunEventKind.RUN_FAILED,
        AgentRunEventKind.RUN_CANCELLED,
        AgentRunEventKind.RUN_TIMED_OUT,
    }:
        code = payload.get("code") or kind.value.lower()
        if not isinstance(code, str):
            raise ValueError("error event requires a safe code")
        return ErrorData(safe_failure_code(code))
    return None

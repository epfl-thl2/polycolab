"""Private fixed-tool gateway for built-in workers; never a browser API."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from polycolab.accounts.authentication import AuthenticationRequired, bearer_token
from polycolab.agents.tools import (
    ALL_TOOL_NAMES,
    DIRECT_TOOL_NAMES,
    ToolCapabilityInvalid,
    execute_tool,
)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, object] = Field(default_factory=dict)


router = APIRouter(prefix="/internal/v1/tools")


@router.post("/call", include_in_schema=False)
def call_tool(payload: ToolRequest, request: Request) -> dict[str, object]:
    token = bearer_token(request.headers.get("authorization"))
    if token is None or payload.name not in ALL_TOOL_NAMES:
        raise AuthenticationRequired
    session = request.app.state.session_factory()
    try:
        invocation = request.headers.get("x-polycolab-tool-invocation")
        if invocation is not None and (not invocation or len(invocation) > 200):
            raise AuthenticationRequired
        source_cursor = request.headers.get("x-polycolab-source-event-cursor")
        writes = DIRECT_TOOL_NAMES | {
            "submit_proposal",
            "submit_verification",
            "cancel_verification",
        }
        if payload.name in writes and (
            invocation is None
            or source_cursor is None
            or len(source_cursor) > 20
            or not source_cursor.isdecimal()
            or int(source_cursor) < 1
        ):
            raise AuthenticationRequired
        if payload.name not in writes and source_cursor is not None:
            raise AuthenticationRequired
        return execute_tool(
            session,
            token=token,
            name=payload.name,
            arguments=payload.arguments,
            idempotency_key=invocation,
            source_event_cursor=int(source_cursor) if source_cursor is not None else None,
            verification_settings=request.app.state.settings,
        )
    except ToolCapabilityInvalid as exc:
        raise AuthenticationRequired from exc
    finally:
        session.close()

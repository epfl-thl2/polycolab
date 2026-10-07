"""HTTP schemas owned by the operations capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from polycolab.entities.enums import AgentRunStatus, AgentSessionStatus, PlatformAgentKind


class OperatorRunDiagnostics(BaseModel):
    """Redacted, operator-only run state; never a transcript or provider view."""

    run_id: UUID
    session_status: AgentSessionStatus
    status: AgentRunStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt: int
    retry_count: int
    lease_generation: int
    lease_active: bool
    lease_expires_at: datetime | None
    agent_kind: PlatformAgentKind
    agent_version: int
    release_sha: str
    runtime_binding_status: str | None
    event_count: int
    first_event_cursor: int | None
    last_event_cursor: int | None
    terminal_outcome: str | None
    failure_class: str | None
    queue_wait_seconds: float | None
    time_to_first_token_seconds: float | None
    duration_seconds: float | None
    usage_input_tokens: int
    usage_output_tokens: int
    usage_total_tokens: int
    capability_total: int
    capability_active: int
    capability_expired: int
    capability_revoked: int
    feature_agent_execution_enabled: bool
    authorization_decision_reason_class: str
    links: dict[str, str]


__all__ = [
    "OperatorRunDiagnostics",
]

"""Database-authoritative pilot admission, reservations, and budget checks."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunUsage,
    SqlExecutionRateWindow,
    SqlHostedModelRequest,
    SqlProject,
    SqlUser,
)
from polycolab.entities.enums import AgentRunStatus


class ExecutionLimitExceeded(Exception):
    def __init__(self, code: str, *, retry_after_seconds: int) -> None:
        self.code = code
        self.retry_after_seconds = max(1, retry_after_seconds)


@dataclass(frozen=True)
class ExecutionLimits:
    user_requests_per_minute: int
    project_requests_per_minute: int
    user_concurrent_runs: int
    project_concurrent_runs: int
    user_daily_tokens: int
    project_daily_tokens: int
    user_daily_cost_microusd: int
    project_daily_cost_microusd: int
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int
    max_run_output_tokens: int
    max_input_tokens_per_round: int
    max_model_rounds: int
    max_attempts: int

    @property
    def round_tokens(self) -> int:
        return self.max_input_tokens_per_round + self.max_run_output_tokens

    @property
    def run_tokens(self) -> int:
        return self.max_attempts * self.max_model_rounds * self.round_tokens

    @property
    def round_cost_microusd(self) -> int:
        numerator = (
            self.max_input_tokens_per_round * self.input_microusd_per_million_tokens
            + self.max_run_output_tokens * self.output_microusd_per_million_tokens
        )
        return (numerator + 999_999) // 1_000_000

    @property
    def run_cost_microusd(self) -> int:
        return self.max_attempts * self.max_model_rounds * self.round_cost_microusd


_ACTIVE = (
    AgentRunStatus.QUEUED,
    AgentRunStatus.CLAIMED,
    AgentRunStatus.RUNNING,
    AgentRunStatus.CANCELLING,
)


def _day(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _minute(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(second=0, microsecond=0)


def _scope_usage(
    session: Session,
    *,
    user_id: UUID | None,
    project_id: UUID | None,
    since: datetime,
    run_id: UUID | None = None,
) -> tuple[int, int, int, int]:
    """Count known usage safely when providers omit individual usage fields."""

    known = func.coalesce(SqlAgentRunUsage.input_tokens, 0) + func.coalesce(
        SqlAgentRunUsage.output_tokens, 0
    )
    tokens = func.greatest(func.coalesce(SqlAgentRunUsage.total_tokens, 0), known)
    unallocated = func.greatest(tokens - known, 0)
    query = select(
        func.coalesce(func.sum(tokens), 0),
        func.coalesce(func.sum(func.coalesce(SqlAgentRunUsage.input_tokens, 0)), 0),
        func.coalesce(func.sum(func.coalesce(SqlAgentRunUsage.output_tokens, 0)), 0),
        func.coalesce(func.sum(unallocated), 0),
    ).join(SqlAgentRun)
    query = query.where(SqlAgentRunUsage.observed_at >= since)
    if user_id is not None:
        query = query.where(SqlAgentRun.requested_by_user_id == user_id)
    if project_id is not None:
        query = query.where(SqlAgentRun.project_id == project_id)
    if run_id is not None:
        query = query.where(SqlAgentRunUsage.run_id == run_id)
    total, input_tokens, output_tokens, unallocated_tokens = session.execute(query).one()
    pending = (
        select(
            func.coalesce(func.sum(SqlHostedModelRequest.input_tokens), 0),
            func.coalesce(func.sum(SqlHostedModelRequest.output_tokens), 0),
        )
        .join(SqlAgentRun)
        .where(
            SqlHostedModelRequest.state == "PENDING", SqlHostedModelRequest.dispatched_at >= since
        )
    )
    if user_id is not None:
        pending = pending.where(SqlAgentRun.requested_by_user_id == user_id)
    if project_id is not None:
        pending = pending.where(SqlAgentRun.project_id == project_id)
    if run_id is not None:
        pending = pending.where(SqlAgentRun.id == run_id)
    pending_input, pending_output = session.execute(pending).one()
    total += pending_input + pending_output
    input_tokens += pending_input
    output_tokens += pending_output
    return (
        int(total or 0),
        int(input_tokens or 0),
        int(output_tokens or 0),
        int(unallocated_tokens or 0),
    )


def _scope_cost(
    session: Session,
    *,
    user_id: UUID | None,
    project_id: UUID | None,
    limits: ExecutionLimits,
    since: datetime,
) -> int:
    legacy = (
        select(SqlAgentRunUsage)
        .join(SqlAgentRun)
        .where(
            SqlAgentRun.runtime_spec["engine"].as_string().is_(None),
            SqlAgentRunUsage.observed_at >= since,
        )
    )
    hosted = (
        select(func.coalesce(func.sum(SqlHostedModelRequest.cost_microusd), 0))
        .join(SqlAgentRun)
        .where(SqlHostedModelRequest.dispatched_at >= since)
    )
    if user_id is not None:
        legacy = legacy.where(SqlAgentRun.requested_by_user_id == user_id)
        hosted = hosted.where(SqlAgentRun.requested_by_user_id == user_id)
    if project_id is not None:
        legacy = legacy.where(SqlAgentRun.project_id == project_id)
        hosted = hosted.where(SqlAgentRun.project_id == project_id)
    cost = int(session.scalar(hosted) or 0)
    for usage in session.scalars(legacy):
        input_tokens, output_tokens = usage.input_tokens or 0, usage.output_tokens or 0
        cost += _cost_microusd(
            limits,
            input_tokens,
            output_tokens,
            max(0, (usage.total_tokens or 0) - input_tokens - output_tokens),
        )
    return cost


def _cost_microusd(
    limits: ExecutionLimits, input_tokens: int, output_tokens: int, unallocated_tokens: int = 0
) -> int:
    numerator = (
        input_tokens * limits.input_microusd_per_million_tokens
        + output_tokens * limits.output_microusd_per_million_tokens
        + unallocated_tokens
        * max(
            limits.input_microusd_per_million_tokens,
            limits.output_microusd_per_million_tokens,
        )
    )
    return (numerator + 999_999) // 1_000_000 if numerator else 0


def _active_runs(
    session: Session,
    *,
    user_id: UUID | None,
    project_id: UUID | None,
    exclude_run_id: UUID | None = None,
) -> int:
    query = select(func.count(SqlAgentRun.id)).where(SqlAgentRun.status.in_(_ACTIVE))
    if user_id is not None:
        query = query.where(SqlAgentRun.requested_by_user_id == user_id)
    if project_id is not None:
        query = query.where(SqlAgentRun.project_id == project_id)
    if exclude_run_id is not None:
        query = query.where(SqlAgentRun.id != exclude_run_id)
    return int(session.scalar(query) or 0)


def _reserved(
    session: Session,
    *,
    user_id: UUID | None,
    project_id: UUID | None,
    limits: ExecutionLimits,
    exclude_run_id: UUID | None = None,
) -> tuple[int, int]:
    query = select(SqlAgentRun).where(SqlAgentRun.status.in_(_ACTIVE))
    if user_id is not None:
        query = query.where(SqlAgentRun.requested_by_user_id == user_id)
    if project_id is not None:
        query = query.where(SqlAgentRun.project_id == project_id)
    if exclude_run_id is not None:
        query = query.where(SqlAgentRun.id != exclude_run_id)
    tokens, cost = 0, 0
    from polycolab.agents.runtime.spec import RuntimeSpec

    for run in session.scalars(query):
        if run.runtime_spec is None:
            tokens += limits.run_tokens
            cost += limits.run_cost_microusd
        else:
            spec = RuntimeSpec.model_validate(run.runtime_spec)
            requests = list(
                session.scalars(
                    select(SqlHostedModelRequest).where(SqlHostedModelRequest.run_id == run.id)
                )
            )
            reserved_tokens = (
                spec.max_attempts
                * spec.max_model_requests
                * (spec.max_input_tokens + spec.max_output_tokens)
            )
            reserved_cost = spec.max_attempts * spec.max_model_requests * spec.round_cost_microusd
            tokens += max(
                0,
                reserved_tokens - sum(item.input_tokens + item.output_tokens for item in requests),
            )
            cost += max(0, reserved_cost - sum(item.cost_microusd for item in requests))
    return tokens, cost


def _consume_window(
    session: Session,
    *,
    scope: str,
    scope_id: UUID,
    limit: int,
    now: datetime,
    error_code: str = "execution_rate_limited",
) -> None:
    if limit <= 0:
        return
    _lock_rate_window_scope(session, scope=scope, scope_id=scope_id)
    start = _minute(now)
    row = session.scalar(
        select(SqlExecutionRateWindow)
        .where(
            SqlExecutionRateWindow.scope == scope,
            SqlExecutionRateWindow.scope_id == scope_id,
            SqlExecutionRateWindow.window_started_at == start,
        )
        .with_for_update()
    )
    if row is None:
        row = SqlExecutionRateWindow(
            scope=scope, scope_id=scope_id, window_started_at=start, count=0
        )
        session.add(row)
        session.flush()
    if row.count >= limit:
        raise ExecutionLimitExceeded(error_code, retry_after_seconds=60 - now.second)
    row.count += 1


def _lock_rate_window_scope(session: Session, *, scope: str, scope_id: UUID) -> None:
    """Serialize first-bucket creation on PostgreSQL without retaining its key.

    Row locks alone cannot protect a previously unseen unique key.  The
    transaction-level advisory lock closes that race for anonymous address
    scopes while remaining a no-op in SQLite's single-process test setup.
    """

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    lock_material = f"{scope}:{scope_id}".encode("ascii")
    lock_key = int.from_bytes(hashlib.sha256(lock_material).digest()[:8], signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def anonymous_address_scope_id(*, client_address: str, hmac_key: str) -> UUID:
    """Return a non-reversible, deployment-scoped identifier for an address."""

    digest = hmac.new(
        hmac_key.encode("utf-8"), client_address.encode("utf-8"), hashlib.sha256
    ).digest()
    return UUID(bytes=digest[:16])


def login_username_scope_id(*, username: str, hmac_key: str) -> UUID:
    """Return a non-reversible identifier for a normalized login name."""

    normalized = username.strip().casefold()
    digest = hmac.new(hmac_key.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).digest()
    return UUID(bytes=digest[:16])


def enforce_public_read_limit(
    session: Session,
    *,
    client_address: str,
    hmac_key: str,
    limit: int,
    now: datetime,
) -> None:
    """Consume one anonymous public-read admission slot.

    The durable row stores only the keyed digest-derived UUID, never the raw
    address or request path.  A limit of zero explicitly disables the gate.
    """

    _consume_window(
        session,
        scope="public_ip",
        scope_id=anonymous_address_scope_id(client_address=client_address, hmac_key=hmac_key),
        limit=limit,
        now=now,
        error_code="public_read_rate_limited",
    )


def enforce_registration_limit(
    session: Session,
    *,
    client_address: str,
    hmac_key: str,
    limit: int,
    now: datetime,
) -> None:
    """Consume a cross-replica registration attempt before password hashing."""

    _consume_window(
        session,
        scope="registration_ip",
        scope_id=anonymous_address_scope_id(client_address=client_address, hmac_key=hmac_key),
        limit=limit,
        now=now,
        error_code="registration_rate_limited",
    )


def enforce_login_address_limit(
    session: Session,
    *,
    client_address: str,
    hmac_key: str,
    limit: int,
    now: datetime,
) -> None:
    """Consume a cross-replica login slot before password hashing."""

    _consume_window(
        session,
        scope="login_ip",
        scope_id=anonymous_address_scope_id(client_address=client_address, hmac_key=hmac_key),
        limit=limit,
        now=now,
        error_code="login_rate_limited",
    )


def enforce_login_username_limit(
    session: Session,
    *,
    username: str,
    hmac_key: str,
    limit: int,
    now: datetime,
) -> None:
    """Consume a deployment-scoped username slot without retaining the name."""

    _consume_window(
        session,
        scope="login_username",
        scope_id=login_username_scope_id(username=username, hmac_key=hmac_key),
        limit=limit,
        now=now,
        error_code="login_rate_limited",
    )


def enforce_sse_reconnect_limit(
    session: Session, *, user_id: UUID, limit: int, now: datetime
) -> None:
    """Consume a cursor-based SSE reconnect slot after authorization succeeds."""

    if limit <= 0:
        return
    # Reuse the canonical user row as the first lock, as run admission does.
    session.scalar(select(SqlUser).where(SqlUser.id == user_id).with_for_update())
    _consume_window(
        session,
        scope="sse_user",
        scope_id=user_id,
        limit=limit,
        now=now,
        error_code="sse_reconnect_rate_limited",
    )


def _over(value: int, limit: int) -> bool:
    return limit > 0 and value > limit


def _remaining_today(now: datetime) -> int:
    return int((_day(now) + timedelta(days=1) - now).total_seconds())


def _lock_scopes(session: Session, *, user_id: UUID, project_id: UUID) -> None:
    # Bound lock waits in synchronous transaction phases, including recovery.
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SET LOCAL statement_timeout = '5s'"))
    # PostgreSQL locks serialize admission and round budget checks for both scopes.
    session.scalar(select(SqlUser).where(SqlUser.id == user_id).with_for_update())
    session.scalar(select(SqlProject).where(SqlProject.id == project_id).with_for_update())


def _require_budget(
    session: Session,
    *,
    user_id: UUID,
    project_id: UUID,
    limits: ExecutionLimits,
    now: datetime,
    additional_tokens: int,
    additional_cost_microusd: int,
    exclude_run_id: UUID | None = None,
    current_remaining_tokens: int = 0,
    current_remaining_cost_microusd: int = 0,
) -> None:
    since = _day(now)
    user_tokens, user_input, user_output, user_unallocated = _scope_usage(
        session, user_id=user_id, project_id=None, since=since
    )
    project_tokens, project_input, project_output, project_unallocated = _scope_usage(
        session, user_id=None, project_id=project_id, since=since
    )
    user_reserved_tokens, user_reserved_cost = _reserved(
        session,
        user_id=user_id,
        project_id=None,
        limits=limits,
        exclude_run_id=exclude_run_id,
    )
    project_reserved_tokens, project_reserved_cost = _reserved(
        session,
        user_id=None,
        project_id=project_id,
        limits=limits,
        exclude_run_id=exclude_run_id,
    )
    if _over(
        user_tokens + user_reserved_tokens + current_remaining_tokens + additional_tokens,
        limits.user_daily_tokens,
    ) or _over(
        project_tokens + project_reserved_tokens + current_remaining_tokens + additional_tokens,
        limits.project_daily_tokens,
    ):
        raise ExecutionLimitExceeded(
            "execution_daily_token_quota_exceeded", retry_after_seconds=_remaining_today(now)
        )
    user_cost = _scope_cost(
        session, user_id=user_id, project_id=None, limits=limits, since=_day(now)
    )
    project_cost = _scope_cost(
        session, user_id=None, project_id=project_id, limits=limits, since=_day(now)
    )
    if _over(
        user_cost + user_reserved_cost + current_remaining_cost_microusd + additional_cost_microusd,
        limits.user_daily_cost_microusd,
    ) or _over(
        project_cost
        + project_reserved_cost
        + current_remaining_cost_microusd
        + additional_cost_microusd,
        limits.project_daily_cost_microusd,
    ):
        raise ExecutionLimitExceeded(
            "execution_daily_cost_quota_exceeded", retry_after_seconds=_remaining_today(now)
        )


def enforce_execution_limits(
    session: Session,
    *,
    user_id: UUID,
    project_id: UUID,
    limits: ExecutionLimits,
    now: datetime,
) -> None:
    """Atomically reserve every possible attempt/round before queueing a run."""

    _lock_scopes(session, user_id=user_id, project_id=project_id)
    _consume_window(
        session, scope="user", scope_id=user_id, limit=limits.user_requests_per_minute, now=now
    )
    _consume_window(
        session,
        scope="project",
        scope_id=project_id,
        limit=limits.project_requests_per_minute,
        now=now,
    )
    _require_budget(
        session,
        user_id=user_id,
        project_id=project_id,
        limits=limits,
        now=now,
        additional_tokens=limits.run_tokens,
        additional_cost_microusd=limits.run_cost_microusd,
    )
    if _over(
        _active_runs(session, user_id=user_id, project_id=None) + 1, limits.user_concurrent_runs
    ):
        raise ExecutionLimitExceeded(
            "execution_concurrent_user_quota_exceeded", retry_after_seconds=1
        )
    if _over(
        _active_runs(session, user_id=None, project_id=project_id) + 1,
        limits.project_concurrent_runs,
    ):
        raise ExecutionLimitExceeded(
            "execution_concurrent_project_quota_exceeded", retry_after_seconds=1
        )


def enforce_next_round_budget(
    session: Session, *, run: SqlAgentRun, limits: ExecutionLimits, now: datetime
) -> None:
    """Fail closed before each provider round if the next bounded round is unsafe."""

    _lock_scopes(session, user_id=run.requested_by_user_id, project_id=run.project_id)
    actual_tokens, actual_input, actual_output, actual_unallocated = _scope_usage(
        session,
        user_id=None,
        project_id=None,
        run_id=run.id,
        since=run.created_at,
    )
    actual_cost = _cost_microusd(limits, actual_input, actual_output, actual_unallocated)
    # The admission reservation is the hard ceiling for one run. A recovered
    # worker derives consumption from immutable usage rows, so it cannot reset
    # a budget by acquiring a new lease generation.
    if _over(actual_tokens + limits.round_tokens, limits.run_tokens) or _over(
        actual_cost + limits.round_cost_microusd, limits.run_cost_microusd
    ):
        raise ExecutionLimitExceeded("execution_run_budget_exceeded", retry_after_seconds=1)
    remaining_tokens = max(limits.run_tokens - actual_tokens, 0)
    remaining_cost = max(limits.run_cost_microusd - actual_cost, 0)
    _require_budget(
        session,
        user_id=run.requested_by_user_id,
        project_id=run.project_id,
        limits=limits,
        now=now,
        additional_tokens=0,
        additional_cost_microusd=0,
        exclude_run_id=run.id,
        current_remaining_tokens=remaining_tokens,
        current_remaining_cost_microusd=remaining_cost,
    )


def purge_expired_rate_windows(
    session: Session,
    *,
    retention: timedelta,
    batch_size: int = 1_000,
    now: datetime,
) -> int:
    """Delete old minute buckets in bounded indexed batches; safe to run repeatedly."""

    if retention <= timedelta(0) or batch_size < 1:
        raise ValueError("positive retention and batch size are required")
    cutoff = now - retention
    ids = list(
        session.scalars(
            select(SqlExecutionRateWindow.id)
            .where(SqlExecutionRateWindow.window_started_at < cutoff)
            .order_by(SqlExecutionRateWindow.window_started_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    if not ids:
        return 0
    session.execute(delete(SqlExecutionRateWindow).where(SqlExecutionRateWindow.id.in_(ids)))
    session.commit()
    return len(ids)

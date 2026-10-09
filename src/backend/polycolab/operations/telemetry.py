"""Typed, content-free primitives for non-execution operational telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlCommunityDeliveryCursor, SqlOutboxEvent
from polycolab.entities.time import utc_now
from polycolab.platform.observability import Metrics

COMMUNITY_CONSUMER_LABEL = "community"
COMMUNITY_SNAPSHOT_STATEMENT_TIMEOUT_MS = 1_000


class PoolRole(StrEnum):
    API = "api"
    COMMUNITY = "community"


class PoolCheckoutOutcome(StrEnum):
    ACQUIRED = "acquired"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class CommunityOutboxSnapshot:
    pending_events: int
    oldest_pending_age_seconds: float


def _bounded_timeout(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 30_000:
        raise ValueError("invalid telemetry statement timeout")
    return value


def community_outbox_snapshot(
    session: Session,
    *,
    now: datetime | None = None,
    statement_timeout_ms: int = COMMUNITY_SNAPSHOT_STATEMENT_TIMEOUT_MS,
) -> CommunityOutboxSnapshot:
    """Return the canonical community backlog without reading event payloads."""

    timeout = _bounded_timeout(statement_timeout_ms)
    observed_at = now or utc_now()
    if observed_at.tzinfo is None:
        raise ValueError("telemetry observation time must be timezone-aware")
    if session.get_bind().dialect.name == "postgresql":
        # Transaction-local and bounded; the caller closes the short read
        # transaction before rendering or performing external I/O.
        session.execute(select(func.set_config("statement_timeout", str(timeout), True)))
    completed = exists(
        select(SqlCommunityDeliveryCursor.event_id).where(
            SqlCommunityDeliveryCursor.event_id == SqlOutboxEvent.id,
            SqlCommunityDeliveryCursor.done.is_(True),
        )
    )
    pending, oldest = session.execute(
        select(func.count(SqlOutboxEvent.id), func.min(SqlOutboxEvent.created_at)).where(~completed)
    ).one()
    pending_count = int(pending or 0)
    if oldest is None:
        return CommunityOutboxSnapshot(pending_count, 0.0)
    if oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=UTC)
    age = max(0.0, (observed_at.astimezone(UTC) - oldest.astimezone(UTC)).total_seconds())
    return CommunityOutboxSnapshot(pending_count, age)


def publish_community_outbox_snapshot(registry: Metrics, snapshot: CommunityOutboxSnapshot) -> None:
    """Publish the two fixed community series and a bounded success outcome."""

    if (
        type(snapshot.pending_events) is not int
        or snapshot.pending_events < 0
        or not math.isfinite(snapshot.oldest_pending_age_seconds)
        or snapshot.oldest_pending_age_seconds < 0
    ):
        raise ValueError("invalid community outbox snapshot")
    registry.set_gauge(
        "polycolab_outbox_pending_events",
        snapshot.pending_events,
        consumer=COMMUNITY_CONSUMER_LABEL,
    )
    registry.set_gauge(
        "polycolab_outbox_oldest_pending_age_seconds",
        snapshot.oldest_pending_age_seconds,
        consumer=COMMUNITY_CONSUMER_LABEL,
    )
    registry.increment(
        "polycolab_operational_snapshot_total",
        source="community_outbox",
        outcome="success",
    )


def record_community_outbox_snapshot_error(registry: Metrics) -> None:
    """Record a content-free failure without retaining or relabeling stale gauges."""

    registry.remove_gauge("polycolab_outbox_pending_events", consumer=COMMUNITY_CONSUMER_LABEL)
    registry.remove_gauge(
        "polycolab_outbox_oldest_pending_age_seconds",
        consumer=COMMUNITY_CONSUMER_LABEL,
    )
    registry.increment(
        "polycolab_operational_snapshot_total",
        source="community_outbox",
        outcome="error",
    )


@dataclass(frozen=True)
class PoolTelemetry:
    """Fixed-label process-local pool observations for Platform wiring."""

    registry: Metrics
    role: PoolRole

    def __post_init__(self) -> None:
        if type(self.role) is not PoolRole:
            raise TypeError("pool telemetry role must use the fixed enum")

    @property
    def _labels(self) -> dict[str, str]:
        return {"role": self.role.value}

    def publish_configuration(self, *, size: int, max_overflow: int) -> None:
        if (
            type(size) is not int
            or not 1 <= size <= 1000
            or type(max_overflow) is not int
            or not 0 <= max_overflow <= 1000
        ):
            raise ValueError("invalid pool telemetry configuration")
        self.registry.set_gauge("polycolab_database_pool_size", size, **self._labels)
        self.registry.set_gauge(
            "polycolab_database_pool_max_overflow", max_overflow, **self._labels
        )

    def set_checked_out(self, value: int) -> None:
        if type(value) is not int or value < 0:
            raise ValueError("invalid checked-out connection count")
        self.registry.set_gauge("polycolab_database_pool_checked_out", value, **self._labels)

    def observe_checkout(self, duration_seconds: float, outcome: PoolCheckoutOutcome) -> None:
        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds < 0
            or type(outcome) is not PoolCheckoutOutcome
        ):
            raise ValueError("invalid pool checkout observation")
        self.registry.observe(
            "polycolab_database_pool_checkout_seconds",
            float(duration_seconds),
            **self._labels,
        )
        self.registry.increment(
            "polycolab_database_pool_checkout_total",
            role=self.role.value,
            outcome=outcome.value,
        )

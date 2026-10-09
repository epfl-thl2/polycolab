"""Small, dependency-free operational metrics with deliberately bounded labels.

The API and worker use this registry for pilot telemetry.  It never accepts
user supplied values as labels, so its Prometheus rendering cannot become a
source of identifiers, prompts, provider URLs, or unbounded cardinality.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from polycolab.db.models import SqlOperationalMetricAggregate
from polycolab.entities.time import utc_now


@dataclass
class _DurationAggregate:
    count: int = 0
    total: float = 0.0
    maximum: float = 0.0


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self._durations: dict[tuple[str, tuple[tuple[str, str], ...]], _DurationAggregate] = (
            defaultdict(_DurationAggregate)
        )
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

    @staticmethod
    def _labels(labels: dict[str, object]) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((key, str(value)) for key, value in labels.items()))

    def increment(self, name: str, amount: int = 1, **labels: object) -> None:
        with self._lock:
            self._counters[name, self._labels(labels)] += amount

    def observe(self, name: str, value: float, **labels: object) -> None:
        with self._lock:
            aggregate = self._durations[name, self._labels(labels)]
            observation = max(0.0, value)
            aggregate.count += 1
            aggregate.total += observation
            aggregate.maximum = max(aggregate.maximum, observation)

    def set_gauge(self, name: str, value: float, **labels: object) -> None:
        with self._lock:
            self._gauges[name, self._labels(labels)] = value

    def adjust_gauge(self, name: str, amount: float, **labels: object) -> None:
        with self._lock:
            key = name, self._labels(labels)
            self._gauges[key] = max(0.0, self._gauges.get(key, 0.0) + amount)

    def remove_gauge(self, name: str, **labels: object) -> None:
        with self._lock:
            self._gauges.pop((name, self._labels(labels)), None)

    def gauge_value(self, name: str, **labels: object) -> float:
        with self._lock:
            return self._gauges.get((name, self._labels(labels)), 0.0)

    def render_prometheus(self) -> str:
        """Render aggregate-only data. Diagnostics must enforce access policy."""

        lines: list[str] = []
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"{name}{self._render_labels(labels)} {value}")
            for (name, labels), gauge_value in sorted(self._gauges.items()):
                lines.append(f"{name}{self._render_labels(labels)} {gauge_value:.6f}")
            for (name, labels), aggregate in sorted(self._durations.items()):
                if aggregate.count == 0:
                    continue
                suffix = self._render_labels(labels)
                lines.extend(
                    (
                        f"{name}_count{suffix} {aggregate.count}",
                        f"{name}_sum{suffix} {aggregate.total:.6f}",
                        f"{name}_max{suffix} {aggregate.maximum:.6f}",
                    )
                )
        return "\n".join(lines) + ("\n" if lines else "")

    @staticmethod
    def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
        if not labels:
            return ""
        safe = (f'{key}="{value.replace(chr(34), "")}"' for key, value in labels)
        return "{" + ",".join(safe) + "}"


metrics = Metrics()


# Only lifecycle telemetry with a bounded, deployment-defined label set is
# persisted.  Never add request, project, user, provider/model, or error-body
# values here: this table is intentionally safe to expose to the internal
# Prometheus scrape endpoint.
_DURABLE_SERIES: dict[str, dict[str, frozenset[str]]] = {
    "polycolab_hosted_recovery_total": {
        "outcome": frozenset({"QUEUED", "CANCELLED", "FAILED", "TIMED_OUT"}),
    },
    "polycolab_hosted_settlement_total": {
        "outcome": frozenset({"COMPLETED", "UNCERTAIN"}),
    },
    "polycolab_run_started_total": {
        "agent_kind": frozenset({"RESEARCHER", "CRITIC"}),
        "outcome": frozenset({"started"}),
    },
    "polycolab_run_terminal_total": {
        "agent_kind": frozenset({"RESEARCHER", "CRITIC"}),
        "outcome": frozenset({"COMPLETED", "CANCELLED", "FAILED", "TIMED_OUT"}),
    },
    "polycolab_run_time_to_first_token_seconds": {
        "agent_kind": frozenset({"RESEARCHER", "CRITIC"}),
        "outcome": frozenset({"first_delta"}),
    },
    "polycolab_run_duration_seconds": {
        "agent_kind": frozenset({"RESEARCHER", "CRITIC"}),
        "outcome": frozenset({"COMPLETED", "CANCELLED", "FAILED", "TIMED_OUT"}),
    },
    "polycolab_run_lease_recovered_total": {
        "outcome": frozenset({"QUEUED", "CANCELLED", "FAILED"}),
    },
    "polycolab_provider_requests_total": {
        "provider_class": frozenset({"configured_gateway"}),
        "outcome": frozenset({"started", "provider_error"}),
    },
}


def _durable_labels(metric_name: str, labels: dict[str, str]) -> tuple[str, dict[str, str]]:
    expected = _DURABLE_SERIES.get(metric_name)
    if expected is None or set(labels) != set(expected):
        raise ValueError("unsupported durable metric series")
    normalized = {key: str(labels[key]) for key in sorted(labels)}
    if any(value not in expected[key] for key, value in normalized.items()):
        raise ValueError("unsupported durable metric label value")
    return "|".join(f"{key}={value}" for key, value in normalized.items()), normalized


def _upsert_values(
    session: Session,
    *,
    metric_name: str,
    labels_key: str,
    labels: dict[str, str],
    counter_increment: int = 0,
    observation: float | None = None,
) -> None:
    """Atomically merge one trusted metric update for SQLite and PostgreSQL."""

    if counter_increment < 0:
        raise ValueError("durable counters cannot decrease")
    if observation is not None and observation < 0:
        raise ValueError("durable observations cannot be negative")
    # SQLAlchemy exposes declarative ``__table__`` as a broad FromClause in
    # type stubs although both dialect upserts require a concrete Table.
    table = cast(Any, SqlOperationalMetricAggregate.__table__)
    now = utc_now()
    value = max(0.0, observation or 0.0)
    insert_values = {
        "id": uuid4(),
        "metric_name": metric_name,
        "labels_key": labels_key,
        "labels": labels,
        "counter_value": counter_increment,
        "observation_count": 1 if observation is not None else 0,
        "observation_sum": value,
        "observation_max": value,
        "updated_at": now,
    }
    excluded_counter = table.c.counter_value + counter_increment
    excluded_count = table.c.observation_count + (1 if observation is not None else 0)
    excluded_sum = table.c.observation_sum + value
    excluded_max = case((table.c.observation_max >= value, table.c.observation_max), else_=value)
    updates = {
        "counter_value": excluded_counter,
        "observation_count": excluded_count,
        "observation_sum": excluded_sum,
        "observation_max": excluded_max,
        "updated_at": now,
    }
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        postgres_statement = (
            postgresql_insert(table)
            .values(**insert_values)
            .on_conflict_do_update(index_elements=("metric_name", "labels_key"), set_=updates)
        )
        session.execute(postgres_statement)
        return
    if dialect == "sqlite":
        sqlite_statement = (
            sqlite_insert(table)
            .values(**insert_values)
            .on_conflict_do_update(index_elements=("metric_name", "labels_key"), set_=updates)
        )
        session.execute(sqlite_statement)
        return
    # The application supports PostgreSQL in deployment and SQLite in tests.
    # Keep a conservative fallback for any future dialect used by a local tool.
    row = (
        session.query(SqlOperationalMetricAggregate)
        .filter_by(metric_name=metric_name, labels_key=labels_key)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        session.add(SqlOperationalMetricAggregate(**insert_values))
        return
    row.counter_value += counter_increment
    if observation is not None:
        row.observation_count += 1
        row.observation_sum += value
        row.observation_max = max(row.observation_max, value)
    row.updated_at = now


def increment_durable(session: Session, metric_name: str, **labels: str) -> None:
    """Add one trusted, cross-process counter update to the current transaction."""

    labels_key, normalized = _durable_labels(metric_name, labels)
    _upsert_values(
        session,
        metric_name=metric_name,
        labels_key=labels_key,
        labels=normalized,
        counter_increment=1,
    )


def observe_durable(session: Session, metric_name: str, value: float, **labels: str) -> None:
    """Add one trusted duration observation to the current transaction."""

    labels_key, normalized = _durable_labels(metric_name, labels)
    _upsert_values(
        session,
        metric_name=metric_name,
        labels_key=labels_key,
        labels=normalized,
        observation=value,
    )


def render_durable_prometheus(session: Session) -> str:
    """Render committed worker/API aggregates without returning database details."""

    lines: list[str] = []
    rows = session.query(SqlOperationalMetricAggregate).order_by(
        SqlOperationalMetricAggregate.metric_name, SqlOperationalMetricAggregate.labels_key
    )
    for row in rows:
        suffix = Metrics._render_labels(tuple(sorted(row.labels.items())))
        if row.counter_value:
            lines.append(f"{row.metric_name}{suffix} {row.counter_value}")
        if row.observation_count:
            lines.extend(
                (
                    f"{row.metric_name}_count{suffix} {row.observation_count}",
                    f"{row.metric_name}_sum{suffix} {row.observation_sum:.6f}",
                    f"{row.metric_name}_max{suffix} {row.observation_max:.6f}",
                )
            )
    return "\n".join(lines) + ("\n" if lines else "")

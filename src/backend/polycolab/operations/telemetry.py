"""Typed, content-free primitives for non-execution operational telemetry."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from polycolab.platform.observability import Metrics


class PoolRole(StrEnum):
    API = "api"


class PoolCheckoutOutcome(StrEnum):
    ACQUIRED = "acquired"
    TIMEOUT = "timeout"


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

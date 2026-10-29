"""Shared non-execution telemetry semantics and bounded labels."""

from typing import Any, cast

import pytest

from polycolab.operations.telemetry import (
    PoolCheckoutOutcome,
    PoolRole,
    PoolTelemetry,
)
from polycolab.platform.observability import Metrics


def test_pool_telemetry_accepts_only_fixed_roles_and_outcomes() -> None:
    registry = Metrics()
    pool = PoolTelemetry(registry, PoolRole.API)
    pool.publish_configuration(size=5, max_overflow=2)
    pool.set_checked_out(3)
    pool.observe_checkout(0.25, PoolCheckoutOutcome.ACQUIRED)
    rendered = registry.render_prometheus()

    assert 'polycolab_database_pool_size{role="api"} 5.000000' in rendered
    assert 'polycolab_database_pool_max_overflow{role="api"} 2.000000' in rendered
    assert 'polycolab_database_pool_checked_out{role="api"} 3.000000' in rendered
    assert 'polycolab_database_pool_checkout_seconds_count{role="api"} 1' in rendered
    assert 'polycolab_database_pool_checkout_total{outcome="acquired",role="api"} 1' in rendered

    with pytest.raises(TypeError):
        PoolTelemetry(registry, cast(Any, "configured-service-name"))
    with pytest.raises(ValueError):
        pool.observe_checkout(float("inf"), PoolCheckoutOutcome.TIMEOUT)

"""Shared non-execution telemetry semantics and bounded labels."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from polycolab.db.models import SqlCommunityDeliveryCursor, SqlOutboxEvent
from polycolab.operations.telemetry import (
    CommunityOutboxSnapshot,
    PoolCheckoutOutcome,
    PoolRole,
    PoolTelemetry,
    community_outbox_snapshot,
    publish_community_outbox_snapshot,
    record_community_outbox_snapshot_error,
)
from polycolab.platform.observability import Metrics
from polycolab.platform.outbox import canonical_digest


def _event(*, created_at: datetime, payload: dict[str, object]) -> SqlOutboxEvent:
    return SqlOutboxEvent(
        id=uuid4(),
        event_type="research.created",
        aggregate_type="OBJECT_REVISION",
        aggregate_id=uuid4(),
        payload=payload,
        payload_digest=canonical_digest(payload),
        created_at=created_at,
    )


def test_community_snapshot_uses_completion_cursor_and_oldest_event(client: TestClient) -> None:
    observed_at = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        pending = _event(
            created_at=observed_at - timedelta(seconds=30),
            payload={"private": "not selected"},
        )
        in_progress = _event(
            created_at=observed_at - timedelta(seconds=10),
            payload={},
        )
        completed = _event(
            created_at=observed_at - timedelta(seconds=60),
            payload={},
        )
        session.add_all((pending, in_progress, completed))
        session.flush()
        session.add_all(
            (
                SqlCommunityDeliveryCursor(event_id=in_progress.id, done=False),
                SqlCommunityDeliveryCursor(event_id=completed.id, done=True),
            )
        )
        session.commit()

        snapshot = community_outbox_snapshot(session, now=observed_at)

    assert snapshot == CommunityOutboxSnapshot(pending_events=2, oldest_pending_age_seconds=30.0)


def test_empty_or_future_community_snapshot_has_nonnegative_age(client: TestClient) -> None:
    observed_at = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        assert community_outbox_snapshot(session, now=observed_at) == CommunityOutboxSnapshot(0, 0)
        event = _event(created_at=observed_at + timedelta(seconds=5), payload={})
        session.add(event)
        session.commit()
        assert community_outbox_snapshot(session, now=observed_at) == CommunityOutboxSnapshot(1, 0)


@pytest.mark.parametrize("timeout", [0, 30_001, True])
def test_snapshot_timeout_is_strictly_bounded(client: TestClient, timeout: int) -> None:
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session, pytest.raises(ValueError):
        community_outbox_snapshot(session, statement_timeout_ms=timeout)


def test_snapshot_publishing_has_only_fixed_content_free_labels() -> None:
    registry = Metrics()
    publish_community_outbox_snapshot(registry, CommunityOutboxSnapshot(3, 12.5))
    rendered = registry.render_prometheus()

    assert 'polycolab_outbox_pending_events{consumer="community"} 3.000000' in rendered
    assert 'polycolab_outbox_oldest_pending_age_seconds{consumer="community"} 12.500000' in rendered
    assert (
        'polycolab_operational_snapshot_total{outcome="success",source="community_outbox"} 1'
        in rendered
    )

    record_community_outbox_snapshot_error(registry)
    rendered = registry.render_prometheus()
    assert "polycolab_outbox_pending_events" not in rendered
    assert "polycolab_outbox_oldest_pending_age_seconds" not in rendered
    assert (
        'polycolab_operational_snapshot_total{outcome="error",source="community_outbox"} 1'
        in rendered
    )


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

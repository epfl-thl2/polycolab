"""Real QueuePool lifecycle checks using SQLite DBAPI, not a PostgreSQL deployment."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import cast
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError

from polycolab.db.session import make_engine
from polycolab.operations.pool_telemetry import PoolMeter
from polycolab.operations.telemetry import PoolRole
from polycolab.platform.config import Settings


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://database.example/polycolab",
        database_pool_size=1,
        database_max_overflow=0,
        database_pool_timeout_seconds=0.03,
    )


@pytest.fixture
def observed() -> Iterator[tuple[PoolMeter, Engine]]:
    meter = PoolMeter(_settings(), PoolRole.API)
    engine = create_engine(
        "sqlite://",
        poolclass=meter.pool_class,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.03,
        connect_args={"check_same_thread": False},
    )
    try:
        yield meter, engine
    finally:
        engine.dispose()


def test_acquisition_timeout_release_and_no_sql(observed: tuple[PoolMeter, Engine]) -> None:
    meter, engine = observed

    def forbid_sql(*args: object) -> None:
        raise AssertionError("pool telemetry must not execute SQL")

    event.listen(engine, "before_cursor_execute", forbid_sql)
    with engine.connect():
        assert 'polycolab_database_pool_checked_out{role="api"} 1.000000' in meter.render(engine)
        with pytest.raises(TimeoutError):
            engine.connect()
    with engine.connect():
        pass
    output = meter.render(engine)
    assert 'polycolab_database_pool_checked_out{role="api"} 0.000000' in output
    assert 'polycolab_database_pool_size{role="api"} 1.000000' in output
    assert 'polycolab_database_pool_max_overflow{role="api"} 0.000000' in output
    assert 'polycolab_database_pool_checkout_total{outcome="acquired",role="api"} 2' in output
    assert 'polycolab_database_pool_checkout_total{outcome="timeout",role="api"} 1' in output
    assert 'polycolab_database_pool_checkout_seconds_count{role="api"} 3' in output
    duration = next(line for line in output.splitlines() if "checkout_seconds_sum" in line)
    assert float(duration.split()[-1]) >= 0.03
    assert "database.example" not in output and "community" not in output


@pytest.mark.parametrize("action", ["invalidate", "detach"])
def test_invalidated_or_detached_connections_do_not_leak_gauge(
    observed: tuple[PoolMeter, Engine], action: str
) -> None:
    meter, engine = observed
    with engine.connect() as connection:
        getattr(connection, action)()
    assert 'polycolab_database_pool_checked_out{role="api"} 0.000000' in meter.render(engine)
    with engine.connect():
        assert 'polycolab_database_pool_checked_out{role="api"} 1.000000' in meter.render(engine)


def test_engine_dispose_recreation_keeps_process_counters(
    observed: tuple[PoolMeter, Engine],
) -> None:
    meter, engine = observed
    with engine.connect():
        pass
    previous = engine.pool
    engine.dispose()
    assert engine.pool is not previous
    with engine.connect():
        pass
    assert 'checkout_total{outcome="acquired",role="api"} 2' in meter.render(engine)


def test_waiting_checkout_recovers_after_return(observed: tuple[PoolMeter, Engine]) -> None:
    meter, engine = observed
    started = Event()

    def acquire() -> None:
        started.set()
        with engine.connect():
            pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        with engine.connect():
            future = executor.submit(acquire)
            assert started.wait(1)
        future.result(timeout=1)
    assert 'checkout_total{outcome="acquired",role="api"} 2' in meter.render(engine)


def test_disposal_gauge_tracks_current_pool_not_retired_connections(
    observed: tuple[PoolMeter, Engine],
) -> None:
    meter, engine = observed
    old = engine.connect()
    try:
        engine.dispose()
        assert 'checked_out{role="api"} 0.000000' in meter.render(engine)
        with engine.connect():
            old.close()
            assert 'checked_out{role="api"} 1.000000' in meter.render(engine)
    finally:
        old.close()


def test_authorized_route_exports_only_its_own_pool(
    observed: tuple[PoolMeter, Engine], client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter, engine = observed
    app = cast(FastAPI, client.app)
    app.state.settings.operator_diagnostics_enabled = True
    app.state.settings.operator_diagnostics_subjects = ["owner"]
    # Keep the fixture's SQLite domain/session database; substitute only the
    # metered engine at the scrape boundary to exercise real QueuePool gauges.
    monkeypatch.setattr(app.state, "pool_meter", meter)
    monkeypatch.setattr(app.state, "engine", engine)
    with engine.connect():
        response = client.get("/internal/v1/metrics", headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'polycolab_database_pool_checked_out{role="api"} 1.000000' in response.text
    assert 'role="community"' not in response.text


def test_connection_failures_are_not_reported_as_pool_timeouts(
    observed: tuple[PoolMeter, Engine],
) -> None:
    meter, engine = observed

    def fail(*args: object) -> None:
        raise RuntimeError("private-connection-details")

    event.listen(engine, "connect", fail)
    with pytest.raises(RuntimeError, match="private-connection-details"):
        engine.connect()
    output = meter.render(engine)
    assert "checkout_total" not in output
    assert "private-connection-details" not in output


def test_engine_factory_passes_pool_class_and_meters_are_isolated(
    observed: tuple[PoolMeter, Engine],
) -> None:
    meter, engine = observed
    settings = _settings()
    community = PoolMeter(settings, PoolRole.COMMUNITY)
    with patch("polycolab.db.session.create_engine") as create:
        make_engine(settings, pool_class=community.pool_class)
    assert create.call_args.kwargs["poolclass"] is community.pool_class
    with pytest.raises(ValueError, match="does not own"):
        community.render(engine)
    assert community.pool_class is not meter.pool_class


def test_sqlite_does_not_advertise_postgresql_pool_budget() -> None:
    settings = Settings(database_url="sqlite:///:memory:")
    meter = PoolMeter(settings, PoolRole.API)
    assert meter.pool_class is None
    engine = make_engine(settings, pool_class=meter.pool_class)
    try:
        with engine.connect():
            assert meter.render(engine) == ""
    finally:
        engine.dispose()

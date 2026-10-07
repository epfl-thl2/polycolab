"""Finite PostgreSQL connection-pool budget and recovery checks."""

import os
from pathlib import Path
from time import monotonic
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, TimeoutError
from sqlalchemy.pool import StaticPool

from polycolab.db.session import make_engine
from polycolab.platform.config import Settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("database_pool_size", 0),
        ("database_pool_size", True),
        ("database_pool_size", 1001),
        ("database_max_overflow", -1),
        ("database_max_overflow", True),
        ("database_max_overflow", 1001),
        ("database_pool_timeout_seconds", 0.0),
        ("database_pool_timeout_seconds", True),
        ("database_pool_timeout_seconds", float("inf")),
        ("database_pool_timeout_seconds", 301.0),
    ],
)
def test_database_pool_settings_are_strict_and_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_postgresql_engine_receives_explicit_pool_budget() -> None:
    settings = Settings(
        database_url="postgresql+psycopg://database.example/polycolab",
        database_pool_size=7,
        database_max_overflow=2,
        database_pool_timeout_seconds=4.5,
    )
    sentinel = object()
    with patch("polycolab.db.session.create_engine", return_value=sentinel) as create:
        assert make_engine(settings) is sentinel
    create.assert_called_once_with(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=7,
        max_overflow=2,
        pool_timeout=4.5,
    )


def test_database_pool_settings_parse_environment_numbers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_POOL_SIZE", "7")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DATABASE_POOL_TIMEOUT_SECONDS", "4.5")
    settings = Settings()
    assert settings.database_pool_size == 7
    assert settings.database_max_overflow == 2
    assert settings.database_pool_timeout_seconds == 4.5


def test_sqlite_keeps_its_existing_static_pool_behavior() -> None:
    engine = make_engine(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            database_pool_size=1,
            database_max_overflow=0,
            database_pool_timeout_seconds=0.1,
        )
    )
    try:
        assert isinstance(engine.pool, StaticPool)
    finally:
        engine.dispose()


def test_sqlite_transaction_mode_preserves_connection_pragmas(tmp_path: Path) -> None:
    engine = make_engine(Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'pragmas.db'}"))
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 10000
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one() == "wal"
            connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(
                "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))"
            )
        with engine.begin() as connection:
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql("INSERT INTO child VALUES (1)")
    finally:
        engine.dispose()


def test_postgresql_pool_exhaustion_waits_finitely_and_recovers() -> None:
    url = os.environ.get("M0_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("M0_POSTGRES_TEST_URL is required for pool exhaustion evidence")
    engine = make_engine(
        Settings(
            database_url=url,
            database_pool_size=1,
            database_max_overflow=0,
            database_pool_timeout_seconds=0.1,
        )
    )
    try:
        with engine.connect():
            started = monotonic()
            with pytest.raises(TimeoutError):
                engine.connect()
            elapsed = monotonic() - started
            assert 0.08 <= elapsed < 1.0
        with engine.connect() as recovered:
            assert recovered.closed is False
    finally:
        engine.dispose()

"""SQLAlchemy engine, pooling, and session lifecycle mechanisms."""

from __future__ import annotations

from sqlite3 import Connection as SqliteConnection

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool

from polycolab.platform.config import Settings


def make_engine(settings: Settings, *, pool_class: type[QueuePool] | None = None) -> Engine:
    if settings.database_url.startswith("sqlite"):
        options: dict[str, object] = {
            "connect_args": {"check_same_thread": False, "timeout": 10, "autocommit": False}
        }
        if ":memory:" in settings.database_url:
            options["poolclass"] = StaticPool
        engine = create_engine(settings.database_url, **options)

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: SqliteConnection, _: object) -> None:
            # Non-legacy transactions keep savepoints inside the outer transaction,
            # including when no write preceded them. PRAGMAs require autocommit.
            dbapi_connection.autocommit = True
            try:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("PRAGMA busy_timeout=10000")
                    if ":memory:" not in settings.database_url:
                        cursor.execute("PRAGMA journal_mode=WAL")
                finally:
                    cursor.close()
            finally:
                dbapi_connection.autocommit = False
            # Keep conservative SQL expressions portable in the local/test
            # database while PostgreSQL uses its native GREATEST function.
            dbapi_connection.create_function("greatest", -1, lambda *values: max(values))

        return engine
    pool_options: dict[str, object] = {}
    if pool_class is not None:
        pool_options["poolclass"] = pool_class
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        **pool_options,
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    from polycolab.research.history import install_history

    install_history()
    return sessionmaker(bind=engine, expire_on_commit=False)


def database_is_ready(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True

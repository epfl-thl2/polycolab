"""Persistent, Docker-free development with explicitly versioned SQLite storage."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from polycolab.operations.bootstrap_admin import run as bootstrap
from polycolab.platform.config import Environment, Settings

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migrations/sqlite"


def upgrade_database(path: Path) -> Path | None:
    """Upgrade without guessing/stamping an unversioned database or losing data."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    head = ScriptDirectory.from_config(config).get_current_head()
    backup = None
    with path.with_suffix(".migration.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        engine = create_engine(f"sqlite+pysqlite:///{path}")
        try:
            with engine.connect() as connection:
                current = MigrationContext.configure(connection).get_current_revision()
                tables = (
                    connection.exec_driver_sql(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'"
                    )
                    .scalars()
                    .all()
                )
                if current is None and any(name != "alembic_version" for name in tables):
                    raise RuntimeError(
                        "Unversioned local database: refusing to stamp or overwrite it."
                    )
                if current is not None:
                    ScriptDirectory.from_config(config).get_revision(current)
                if current == head:
                    return None
            if path.exists() and tables:
                backups = path.parent / "backups"
                backups.mkdir(exist_ok=True, mode=0o700)
                timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
                backup = backups / f"{path.stem}-{timestamp}-{uuid4().hex[:8]}.db"
                with sqlite3.connect(path) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
                backup.chmod(0o600)
            with engine.connect() as connection:
                # Explicit BEGIN makes SQLite DDL transactional, including table rebuilds.
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.commit()
                connection.exec_driver_sql("BEGIN IMMEDIATE")
                config.attributes["connection"] = connection
                try:
                    command.upgrade(config, "head")
                    if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
                        raise RuntimeError("Local migration produced invalid foreign keys")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
            path.chmod(0o600)
            return backup
        finally:
            engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    expected = ROOT / ".local/polycolab.db"
    if (
        settings.app_env is not Environment.LOCAL
        or settings.database_url != f"sqlite+pysqlite:///{expected}"
    ):
        raise RuntimeError("Use pnpm run dev:local to select the local database explicitly.")
    backup = upgrade_database(expected)
    if backup:
        print(f"Database backup: {backup}")
    if args.migrate_only:
        return
    try:
        bootstrap(settings)
    except ValueError:
        if settings.bootstrap_admin_password is not None:
            raise
        if not sys.stdin.isatty():
            raise RuntimeError(
                "First startup requires BOOTSTRAP_ADMIN_PASSWORD or an interactive terminal."
            ) from None
        password = getpass.getpass("Choose the initial admin password (at least 12 characters): ")
        confirm = getpass.getpass("Confirm admin password: ")
        if password != confirm:
            raise RuntimeError("Passwords do not match.") from None
        from pydantic import SecretStr

        bootstrap(settings.model_copy(update={"bootstrap_admin_password": SecretStr(password)}))
    print(f"Local data: {expected.parent}")


if __name__ == "__main__":
    main()

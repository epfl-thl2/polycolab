"""Keyed, content-free canonical database manifests for isolated restore drills."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.orm import Session

import polycolab.db.models  # noqa: F401  # register the complete canonical schema
from polycolab.db.base import metadata
from polycolab.db.session import make_engine, make_session_factory
from polycolab.platform.config import get_settings

FORMAT = "polycolab-recovery-integrity-v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024

# These tables are explicitly rebuildable/operational projections. Everything
# else in model metadata is canonical and joins the manifest automatically when
# a migration adds a new table.
DERIVED_TABLES = frozenset(
    {
        "community_delivery_cursors",
        "execution_rate_windows",
        "operational_metric_aggregates",
        "operator_diagnostic_accesses",
        "outbox_consumer_receipts",
        "research_notifications",
        "research_progress_summaries",
    }
)
CANONICAL_TABLES = tuple(sorted(set(metadata.tables) - DERIVED_TABLES))


def _part(digest: hmac.HMAC, tag: bytes, value: bytes) -> None:
    digest.update(tag)
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _encoded(value: object) -> tuple[bytes, bytes]:
    if value is None:
        return b"n", b""
    if isinstance(value, bool):
        return b"b", b"1" if value else b"0"
    if isinstance(value, Enum):
        return _encoded(value.value)
    if isinstance(value, UUID):
        return b"u", value.bytes
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return b"t", value.astimezone(UTC).isoformat(timespec="microseconds").encode()
    if isinstance(value, date):
        return b"d", value.isoformat().encode("ascii")
    if isinstance(value, int):
        return b"i", str(value).encode("ascii")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite database value")
        return b"f", value.hex().encode("ascii")
    if isinstance(value, Decimal):
        return b"q", str(value).encode("ascii")
    if isinstance(value, str):
        return b"s", value.encode("utf-8")
    if isinstance(value, bytes):
        return b"x", value
    if isinstance(value, memoryview):
        return b"x", bytes(value)
    if isinstance(value, (list, dict)):
        return b"j", json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    raise ValueError("unsupported canonical database value")


def _table_manifest(session: Session, table: Table, key: bytes) -> dict[str, object]:
    primary_key = list(table.primary_key.columns)
    if not primary_key:
        raise ValueError("canonical table requires a primary key")
    digest = hmac.new(key, digestmod=hashlib.sha256)
    _part(digest, b"T", table.name.encode("ascii"))
    columns = list(table.columns)
    for column in columns:
        _part(digest, b"C", column.name.encode("ascii"))
    rows = 0
    result = session.execute(select(*columns).order_by(*primary_key)).yield_per(1000)
    for row in result:
        digest.update(b"R")
        for value in row:
            tag, encoded = _encoded(value)
            _part(digest, tag, encoded)
        rows += 1
    return {"rows": rows, "hmac_sha256": digest.hexdigest()}


def capture_manifest(
    session: Session,
    *,
    key: bytes,
    schema_revision: str,
    table_names: Sequence[str] = CANONICAL_TABLES,
    schema: MetaData = metadata,
) -> dict[str, object]:
    """Stream a deterministic keyed manifest without returning canonical values."""

    if not 32 <= len(key) <= 4096:
        raise ValueError("recovery manifest key must contain 32-4096 bytes")
    if not schema_revision or len(schema_revision) > 200:
        raise ValueError("an explicit bounded schema revision is required")
    names = tuple(sorted(table_names))
    if len(names) != len(set(names)) or any(name not in schema.tables for name in names):
        raise ValueError("manifest table set must be unique and registered")
    return {
        "format": FORMAT,
        "schema_revision": schema_revision,
        "excluded_derived_tables": sorted(DERIVED_TABLES),
        "tables": {name: _table_manifest(session, schema.tables[name], key) for name in names},
    }


def manifest_mismatches(
    expected: Mapping[str, object], actual: Mapping[str, object]
) -> tuple[str, ...]:
    """Return bounded schema/table labels only; never echo manifest values."""

    if expected.get("format") != FORMAT or actual.get("format") != FORMAT:
        return ("$format",)
    mismatches: list[str] = []
    if expected.get("schema_revision") != actual.get("schema_revision"):
        mismatches.append("$schema_revision")
    if expected.get("excluded_derived_tables") != actual.get("excluded_derived_tables"):
        mismatches.append("$excluded_derived_tables")
    expected_tables = expected.get("tables")
    actual_tables = actual.get("tables")
    if not isinstance(expected_tables, dict) or not isinstance(actual_tables, dict):
        return tuple(mismatches + ["$tables"])
    for name in sorted(set(expected_tables) | set(actual_tables)):
        if name not in metadata.tables or expected_tables.get(name) != actual_tables.get(name):
            mismatches.append(name if name in metadata.tables else "$tables")
    return tuple(dict.fromkeys(mismatches))


def _capture_database(key: bytes) -> dict[str, object]:
    settings = get_settings()
    engine = make_engine(settings)
    try:
        factory = make_session_factory(engine)
        with factory() as session:
            connection = session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
            if connection.dialect.name != "postgresql":
                raise ValueError("recovery manifests require PostgreSQL")
            session.execute(text("SET TRANSACTION READ ONLY"))
            revision = session.scalar(text("SELECT version_num FROM alembic_version"))
            if not isinstance(revision, str):
                raise ValueError("schema revision unavailable")
            return capture_manifest(session, key=key, schema_revision=revision)
    finally:
        engine.dispose()


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("invalid manifest file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid manifest file")
    return value


def _write_new(path: Path, manifest: Mapping[str, object]) -> None:
    payload = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds bounded output")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--expected", type=Path, required=True)
    args = parser.parse_args(argv)
    secret = os.environ.get("RECOVERY_MANIFEST_HMAC_KEY", "").encode("utf-8")
    try:
        actual = _capture_database(secret)
        if args.command == "capture":
            _write_new(args.output, actual)
            report: dict[str, Any] = {"status": "CAPTURED"}
        else:
            mismatches = manifest_mismatches(_read_manifest(args.expected), actual)
            report = {"status": "MATCH" if not mismatches else "MISMATCH"}
            if mismatches:
                report["sections"] = list(mismatches)
    except Exception:
        print(json.dumps({"status": "RECOVERY_INTEGRITY_FAILURE"}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"CAPTURED", "MATCH"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

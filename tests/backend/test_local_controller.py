"""Local startup must wait for this controller, not a stale advertisement."""

import json
import runpy
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("incarnation", "capacity", "seconds", "healthy"),
    [
        ("new", 2, 30, True),
        ("old", 2, 30, False),
        ("new", 0, 30, False),
        ("new", 2, -30, False),
    ],
)
def test_controller_heartbeat_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    incarnation: str,
    capacity: int,
    seconds: int,
    healthy: bool,
) -> None:
    config = tmp_path / "controller.toml"
    config.write_text(
        'worker_id = "local-codex"\n[[images]]\nlanguage = "AGENT"\n'
        'reference = "codex@sha256:digest"\n'
    )
    database = tmp_path / "local.db"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE hosted_executors (worker_id, image_digest, protocol_version, "
            "sandbox_backend, sandbox_version, expires_at, capacity, incarnation)"
        )
        db.execute(
            "INSERT INTO hosted_executors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "local-codex",
                "digest",
                7,
                "microsandbox",
                "0.6.18",
                (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat(),
                capacity,
                incarnation,
            ),
        )
    helper = Path(__file__).resolve().parents[2] / "scripts/development-controller.py"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(helper),
            "health",
            str(config),
            "--database",
            str(database),
            "--previous-incarnation",
            "old",
        ],
    )
    runpy.run_path(str(helper), run_name="__main__")
    assert json.loads(capsys.readouterr().out)["healthy"] is healthy

"""Deployment ordering and fail-closed migration checks without live containers."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from polycolab.operations import migrate
from polycolab.platform.config import Environment, Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode,worker", [("build", False), ("pull", True), ("reuse", False)])
def test_launcher_runs_migration_before_core(tmp_path: Path, mode: str, worker: bool) -> None:
    result, calls = launch(tmp_path, mode=mode, worker=worker)
    assert result.returncode == 0, result.stderr
    migration = next(i for i, args in enumerate(calls) if "run" in args)
    assert calls[migration][-8:] == [
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "core",
        "python",
        "-m",
        "polycolab.operations.migrate",
    ]
    assert "polycolab.operations.migrate" in calls[migration]
    assert calls[migration - 1][-5:] == ["up", "-d", "--wait", "postgres", "object-storage"]
    assert calls[migration - 2][-3:] == ["stop", "worker", "core"]
    assert calls[-1][-1] == ("worker" if worker else "core")
    assert "--force-recreate" in calls[-1]
    assert all(
        args[:6] == ["compose", "--env-file", "private settings.env", "-f", "stack.yml", "-p"]
        for args in calls
    )
    if mode == "build":
        assert any("build" in args for args in calls[:migration])
    elif mode == "pull":
        assert any("pull" in args for args in calls[:migration])


def test_migration_failure_leaves_core_stopped(tmp_path: Path) -> None:
    result, calls = launch(tmp_path, migration_failure=True)
    assert result.returncode == 17
    assert calls[-1][-1] == "polycolab.operations.migrate"
    assert not any("--force-recreate" in args for args in calls)


@pytest.mark.parametrize(
    "legacy", ["api", "garage", "migrate", "community", "execution-reconciler"]
)
def test_legacy_containers_require_preservation_before_upgrade(tmp_path: Path, legacy: str) -> None:
    result, calls = launch(tmp_path, legacy=legacy)
    assert result.returncode == 1
    assert "Legacy Compose containers" in result.stderr
    assert not any(
        command in args for args in calls for command in ("stop", "up", "run", "build", "pull")
    )


def launch(
    directory: Path,
    *,
    mode: str = "reuse",
    worker: bool = False,
    migration_failure: bool = False,
    legacy: str = "",
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    docker = directory / "docker"
    log = directory / "calls.jsonl"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['TEST_DOCKER_LOG'], 'a') as output:\n"
        "    output.write(json.dumps(args) + '\\n')\n"
        "if 'ps' in args: print(os.environ['TEST_LEGACY'])\n"
        "if '--services' in args: print(os.environ['TEST_SERVICES'])\n"
        "if 'run' in args: sys.exit(int(os.environ['TEST_MIGRATION_EXIT']))\n"
    )
    docker.chmod(0o700)
    env = {
        **os.environ,
        "PATH": str(directory) + os.pathsep + os.environ["PATH"],
        "TEST_DOCKER_LOG": str(log),
        "TEST_LEGACY": legacy,
        "TEST_SERVICES": "postgres\nobject-storage\ncore" + ("\nworker" if worker else ""),
        "TEST_MIGRATION_EXIT": "17" if migration_failure else "0",
    }
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "deploy/scripts/deploy-stack.sh"),
            mode,
            "--env-file",
            "private settings.env",
            "-f",
            "stack.yml",
            "-p",
            "isolated",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, [json.loads(line) for line in log.read_text().splitlines()]


@pytest.mark.parametrize(
    "environment,preflight_code,expected",
    [(Environment.LOCAL, 1, 0), (Environment.PRODUCTION, 0, 0), (Environment.PRODUCTION, 1, 1)],
)
def test_migration_preserves_production_preflight(
    monkeypatch: pytest.MonkeyPatch, environment: Environment, preflight_code: int, expected: int
) -> None:
    settings = Settings().model_copy(update={"app_env": environment})
    calls: list[str] = []
    monkeypatch.setattr(migrate, "get_settings", lambda: settings)

    def preflight(args: list[str]) -> int:
        calls.append("preflight")
        assert args == []
        return preflight_code

    def run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        calls.append("alembic")
        assert args == ["alembic", "upgrade", "head"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(migrate, "preflight", preflight)
    monkeypatch.setattr("polycolab.operations.migrate.subprocess.run", run)
    assert migrate.main() == expected
    assert calls == (
        ["alembic"]
        if environment is Environment.LOCAL
        else ["preflight"]
        if preflight_code
        else ["preflight", "alembic"]
    )

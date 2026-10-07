"""Rendered Compose models must preserve volumes and isolate production settings."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_compose_paths_and_production_isolation(tmp_path: Path) -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("Docker Compose CLI is not installed")
    directory = tmp_path / "deploy/docker"
    garage = tmp_path / "deploy/garage"
    directory.mkdir(parents=True)
    garage.mkdir()
    for name in ("compose.yml", "compose.production.yml"):
        shutil.copyfile(ROOT / "deploy/docker" / name, directory / name)
    for name in ("compose.yaml", "garage.toml"):
        shutil.copyfile(ROOT / "deploy/garage" / name, garage / name)
    (directory / ".env").write_text("APP_ENV=local\nREGISTRATION_MODE=open\n")
    private = tmp_path / "private.env"
    private.write_text("APP_ENV=production\nREGISTRATION_MODE=closed\n")
    empty = tmp_path / "empty.env"
    empty.write_text("")
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "")}

    def model(arguments: list[str], environment: dict[str, str]) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads(
                subprocess.check_output(
                    [docker, "compose", *arguments, "config", "--format", "json"],
                    cwd=tmp_path,
                    env=environment,
                    text=True,
                )
            ),
        )

    local = model(
        [
            "--env-file",
            str(directory / ".env"),
            "--profile",
            "execution",
            "-f",
            str(directory / "compose.yml"),
        ],
        env,
    )
    assert local["name"] == "polycolab"
    assert local["volumes"]["postgres-data"]["name"] == "polycolab_postgres-data"
    assert Path(local["services"]["garage"]["volumes"][0]["source"]).is_file()
    for name in ("api", "migrate", "community", "execution-reconciler"):
        service = local["services"][name]
        assert service["environment"]["REGISTRATION_MODE"] == "open"
        assert "@postgres:5432/" in service["environment"]["DATABASE_URL"]
        assert Path(service["build"]["context"]) == tmp_path
    assert not any(
        key.startswith("DATABASE_") for key in local["services"]["worker"]["environment"]
    )
    (directory / ".env").unlink()  # Production must work without any development file.
    production_env = {
        **env,
        "POLYCOLAB_ENV_FILE": str(private),
        "POLYCOLAB_IMAGE": "polycolab:test",
        "POSTGRES_PASSWORD": "test",
        "GARAGE_RPC_SECRET": "test",
        "GARAGE_DEFAULT_ACCESS_KEY": "test",
        "GARAGE_DEFAULT_SECRET_KEY": "test",
        "RUNTIME_WORKER_TOKEN": "test",
    }
    production = model(
        [
            "--env-file",
            str(empty),
            "-f",
            str(directory / "compose.yml"),
            "-f",
            str(directory / "compose.production.yml"),
        ],
        production_env,
    )
    for name in ("api", "migrate", "community", "execution-reconciler"):
        service = production["services"][name]
        expected = {"APP_ENV": "production", "REGISTRATION_MODE": "closed"}
        if name == "execution-reconciler":
            expected.update(
                DATABASE_POOL_SIZE="2", DATABASE_MAX_OVERFLOW="0", DATABASE_POOL_TIMEOUT_SECONDS="5"
            )
        assert service["environment"] == expected
        assert "build" not in service

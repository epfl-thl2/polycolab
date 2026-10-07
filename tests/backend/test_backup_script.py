"""Filesystem/process failure checks with fake tools, not backup/restore evidence."""

import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from polycolab.operations.backup import verify_bundle

SCRIPT = Path(__file__).resolve().parents[2] / "deploy/scripts/backup-postgres.sh"


@pytest.fixture
def backup_env(tmp_path: Path) -> dict[str, str]:
    tools = tmp_path / "bin"
    tools.mkdir()
    scripts = {
        "pg_dump": """#!/bin/sh
if [ -n "${PGSERVICE:-}" ]; then
  [ "$#" = 3 ] || exit 7
fi
printf 'synthetic-private-dump'
printf 'synthetic-secret-diagnostic' >&2
exit "${TEST_DUMP_EXIT:-0}"
""",
        "age": """#!/bin/sh
# Confirm encryption receives stdin, not an already-written plaintext file.
[ "$#" = 3 ] && [ "$1" = --encrypt ] && [ "$2" = --recipient ] || exit 9
data=$(cat)
[ "$data" = synthetic-private-dump ] || exit 8
printf 'synthetic-encrypted-output'
printf 'synthetic-secret-diagnostic' >&2
exit "${TEST_AGE_EXIT:-0}"
""",
        "date": """#!/bin/sh
printf '20260908T120000Z'
""",
    }
    for name, content in scripts.items():
        path = tools / name
        path.write_text(content)
        path.chmod(0o700)
    return {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "DATABASE_URL": "postgresql+psycopg://test:synthetic-password@invalid/test",
        "APP_ENV": "production",
        "BACKUP_ENCRYPTION_RECIPIENT": "synthetic-recipient",
    }


def run_backup(destination: Path, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(destination)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_encrypted_backup_is_private_and_contains_no_plaintext(
    tmp_path: Path, backup_env: dict[str, str]
) -> None:
    destination = tmp_path / "backups"
    result = run_backup(destination, backup_env)
    assert result.returncode == 0
    bundle = next(destination.iterdir())
    assert verify_bundle(bundle) is True
    assert bundle.stat().st_mode & 0o777 == 0o700
    assert sorted(path.name for path in bundle.iterdir()) == [
        "COMPLETE",
        "postgres.dump.age",
        "postgres.dump.age.sha256",
    ]
    for path in bundle.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert b"synthetic-private-dump" not in path.read_bytes()
    expected = hashlib.sha256(b"synthetic-encrypted-output").hexdigest()
    assert (bundle / "postgres.dump.age.sha256").read_text().split() == [
        expected,
        "postgres.dump.age",
    ]
    assert "synthetic-password" not in result.stdout + result.stderr
    assert "synthetic-secret-diagnostic" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["TEST_DUMP_EXIT", "TEST_AGE_EXIT"])
def test_pipeline_failure_cleans_only_its_own_files(
    tmp_path: Path, backup_env: dict[str, str], failure: str
) -> None:
    destination = tmp_path / "backups"
    destination.mkdir()
    preserved = destination / "existing-backup"
    preserved.write_bytes(b"keep")
    result = run_backup(destination, {**backup_env, failure: "1"})
    assert result.returncode != 0
    assert list(destination.iterdir()) == [preserved]
    assert preserved.read_bytes() == b"keep"
    assert "synthetic-secret-diagnostic" not in result.stdout + result.stderr


def test_same_second_concurrent_runs_do_not_overwrite(
    tmp_path: Path, backup_env: dict[str, str]
) -> None:
    destination = tmp_path / "backups"
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_backup(destination, backup_env), range(2)))
    assert all(result.returncode == 0 for result in results)
    bundles = list(destination.iterdir())
    assert len(bundles) == 2
    assert all((bundle / "COMPLETE").is_file() for bundle in bundles)


def test_local_plaintext_is_explicit_and_nonlocal_requires_encryption(
    tmp_path: Path, backup_env: dict[str, str]
) -> None:
    environment = {**backup_env, "BACKUP_ENCRYPTION_RECIPIENT": ""}
    destination = tmp_path / "backups"
    result = run_backup(destination, environment)
    assert result.returncode != 0
    assert not destination.exists()
    result = run_backup(destination, {**environment, "APP_ENV": "local"})
    assert result.returncode == 0
    bundle = next(destination.iterdir())
    assert verify_bundle(bundle) is False
    assert (bundle / "postgres.dump").read_bytes() == b"synthetic-private-dump"


def test_checksum_failure_does_not_publish_complete_bundle(
    tmp_path: Path, backup_env: dict[str, str]
) -> None:
    checksum = tmp_path / "bin/sha256sum"
    checksum.write_text("#!/bin/sh\nexit 1\n")
    checksum.chmod(0o700)
    destination = tmp_path / "backups"
    result = run_backup(destination, backup_env)
    assert result.returncode != 0
    assert list(destination.iterdir()) == []


def test_service_connection_does_not_pass_credentials_in_arguments(
    tmp_path: Path, backup_env: dict[str, str]
) -> None:
    environment = {**backup_env, "DATABASE_URL": "", "PGSERVICE": "backup"}
    result = run_backup(tmp_path / "backups", environment)
    assert result.returncode == 0
    result = run_backup(tmp_path / "ambiguous", {**backup_env, "PGSERVICE": "backup"})
    assert result.returncode != 0
    assert not (tmp_path / "ambiguous").exists()

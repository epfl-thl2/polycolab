"""Restore preflight checks with fake tools; never creates a database."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "deploy/scripts"


@pytest.mark.parametrize("script", ["restore-postgres.sh", "verify-restore.sh"])
@pytest.mark.parametrize(
    "url",
    [
        "postgresql://localhost/polycolab_restore_test?dbname=canonical",
        "postgresql://localhost/polycolab_restore_test?host=remote.example",
        "postgresql://localhost/polycolab_restore_test#ignored",
        "postgresql://localhost/nested/polycolab_restore_test",
        "mysql://localhost/polycolab_restore_test",
    ],
)
def test_ambiguous_restore_urls_fail_even_in_dry_run(script: str, url: str) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPTS / script), "--dump", "missing", "--database-url", url, "--dry-run"],
        env={"PATH": os.environ["PATH"], "APP_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert url not in result.stdout + result.stderr


@pytest.mark.parametrize("script", ["restore-postgres.sh", "verify-restore.sh"])
def test_explicit_loopback_target_dry_run(script: str) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / script),
            "--dump",
            "missing",
            "--database-url",
            "postgresql+psycopg://test:synthetic-secret@[::1]:5432/polycolab_restore_test",
            "--dry-run",
        ],
        env={"PATH": os.environ["PATH"], "APP_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert "synthetic-secret" not in result.stdout + result.stderr


@pytest.mark.parametrize("failure", ["archive", "query", "unexpected", "preexisting"])
def test_failed_preflight_never_creates_or_drops_target(tmp_path: Path, failure: str) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    for name, body in {
        "pg_restore": '[ "$TEST_FAILURE" != archive ]',
        "psql": 'if [ "$TEST_FAILURE" = query ]; then exit 1; fi\n'
        'if [ "$TEST_FAILURE" = unexpected ]; then printf invalid; fi\n'
        'if [ "$TEST_FAILURE" = preexisting ]; then printf 1; fi',
        "createdb": 'printf created >> "$TEST_CALLS"',
        "dropdb": 'printf dropped >> "$TEST_CALLS"',
    }.items():
        tool = tools / name
        tool.write_text("#!/bin/sh\n" + body + "\n")
        tool.chmod(0o700)
    dump = tmp_path / "synthetic.dump"
    dump.write_bytes(b"synthetic archive")
    result = subprocess.run(
        [
            "bash",
            str(
                SCRIPTS
                / ("verify-restore.sh" if failure == "preexisting" else "restore-postgres.sh")
            ),
            "--dump",
            str(dump),
            "--database-url",
            "postgresql://localhost/polycolab_restore_test",
            *([] if failure == "preexisting" else ["--replace"]),
        ],
        env={
            "PATH": f"{tools}:{os.environ['PATH']}",
            "APP_ENV": "local",
            "RESTORE_CONFIRM": "YES",
            "TEST_FAILURE": failure,
            "TEST_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (2 if failure == "preexisting" else 1)
    assert not calls.exists()


@pytest.mark.parametrize("failure", ["none", "metadata", "manifest", "research"])
@pytest.mark.parametrize("use_manifest", [True, False])
def test_drill_cleans_only_after_all_verification(
    tmp_path: Path, failure: str, use_manifest: bool
) -> None:
    if not use_manifest and failure == "manifest":
        failure = "none"
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    for name, body in {
        "pg_restore": "exit 0",
        "psql": 'case "$*" in\n'
        "*pg_database*) exit 0 ;;\n"
        "*pg_class*) printf 10 ;;\n"
        '*alembic_version*) [ "$TEST_FAILURE" != metadata ] ;;\n'
        "*) exit 0 ;;\nesac",
        "createdb": 'printf "created\\n" >> "$TEST_CALLS"',
        "dropdb": 'printf "dropped\\n" >> "$TEST_CALLS"',
        "uv": 'case "$DATABASE_URL" in\n'
        "postgresql://localhost/polycolab_restore_*) ;;\n"
        "*) exit 9 ;;\nesac\n"
        'case "$*" in\n'
        '*polycolab.recovery_integrity*) printf "compared\\n" >> "$TEST_CALLS"; '
        '[ "$TEST_FAILURE" != manifest ] ;;\n'
        '*"polycolab.recovery_dependencies research --isolated-restore '
        '--max-items $TEST_BOUND"*) printf "research\\n" >> "$TEST_CALLS"; '
        '[ "$TEST_FAILURE" != research ] ;;\n'
        "*) exit 9 ;;\nesac",
    }.items():
        tool = tools / name
        tool.write_text("#!/bin/sh\n" + body + "\n")
        tool.chmod(0o700)
    dump = tmp_path / "synthetic.dump"
    dump.write_bytes(b"synthetic")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "verify-restore.sh"),
            "--dump",
            str(dump),
            "--database-url",
            "postgresql://localhost/source",
            *(["--manifest", str(manifest)] if use_manifest else ["--research-max-items", "17"]),
        ],
        env={
            "PATH": f"{tools}:{os.environ['PATH']}",
            "APP_ENV": "local",
            "DATABASE_URL": "postgresql://localhost/not_the_target",
            "RECOVERY_MANIFEST_HMAC_KEY": "synthetic-key-" * 4,
            "TEST_FAILURE": failure,
            "TEST_CALLS": str(calls),
            "TEST_BOUND": "1000" if use_manifest else "17",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (0 if failure == "none" else 1)
    expected = ["created"]
    if failure != "metadata" and use_manifest:
        expected.append("compared")
    if failure not in {"metadata", "manifest"}:
        expected.append("research")
    if failure == "none":
        expected.append("dropped")
    assert calls.read_text().splitlines() == expected
    assert "synthetic-key" not in result.stdout + result.stderr


@pytest.mark.parametrize("bound", ["0", "-1", "1000001", "01", "bad", "1+1"])
def test_research_bound_is_validated_before_restore(bound: str) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "verify-restore.sh"),
            "--dump",
            "missing",
            "--database-url",
            "postgresql://localhost/source",
            "--research-max-items",
            bound,
            "--dry-run",
        ],
        env={"PATH": os.environ["PATH"], "APP_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert "Research verification bound must be 1-1000000" in result.stderr


@pytest.mark.parametrize("kind", ["artifacts", "credentials"])
@pytest.mark.parametrize("bound", ["0", "-1", "1000001", "01", "bad", "1+1"])
def test_dependency_bounds_fail_before_restore(kind: str, bound: str) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "verify-restore.sh"),
            "--dump",
            "missing",
            "--database-url",
            "postgresql://localhost/source",
            f"--{kind}-max-items",
            bound,
            "--isolated-dependencies",
            "--dry-run",
        ],
        env={"PATH": os.environ["PATH"], "APP_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert "Dependency verification bounds must be 1-1000000" in result.stderr


@pytest.mark.parametrize(
    "options",
    [["--artifacts-max-items", "1"], ["--credentials-max-items", "1"], ["--isolated-dependencies"]],
)
def test_dependencies_require_explicit_isolation_acknowledgment(options: list[str]) -> None:
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "verify-restore.sh"),
            "--dump",
            "missing",
            "--database-url",
            "postgresql://localhost/source",
            *options,
            "--dry-run",
        ],
        env={"PATH": os.environ["PATH"], "APP_ENV": "local"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 2
    assert "--isolated-dependencies" in result.stderr


@pytest.mark.parametrize(
    ("selected", "failure", "keep"),
    [
        ("artifacts", "none", False),
        ("credentials", "none", False),
        ("both", "none", False),
        ("both", "none", True),
        ("both", "artifacts", False),
        ("both", "credentials", False),
        ("both", "artifacts_limit", False),
        ("both", "credentials_limit", False),
    ],
)
def test_dependency_checks_use_exact_restore_and_gate_cleanup(
    tmp_path: Path, selected: str, failure: str, keep: bool
) -> None:
    tools = tmp_path / "bin"
    tools.mkdir()
    calls = tmp_path / "calls"
    target = tmp_path / "target"
    for name, body in {
        "pg_restore": "exit 0",
        "psql": 'case "$*" in\n'
        "*pg_database*) exit 0 ;;\n"
        "*pg_class*) printf 10 ;;\n"
        "*) exit 0 ;;\nesac",
        "createdb": 'for arg do printf "%s" "$arg" > "$TEST_TARGET"; done\n'
        'printf "created\\n" >> "$TEST_CALLS"',
        "dropdb": 'printf "dropped\\n" >> "$TEST_CALLS"',
        "uv": 'expected="postgresql://localhost/$(cat "$TEST_TARGET")"\n'
        '[ "$DATABASE_URL" = "$expected" ] || exit 9\n'
        'case "$*" in\n'
        '*"polycolab.recovery_integrity compare --expected "*) kind=manifest ;;\n'
        '*"polycolab.recovery_dependencies research --isolated-restore --max-items 1000") '
        "kind=research ;;\n"
        '*"polycolab.recovery_dependencies artifacts --isolated-restore --max-items 17") '
        "kind=artifacts ;;\n"
        '*"polycolab.recovery_dependencies credentials --isolated-restore --max-items 23") '
        "kind=credentials ;;\n"
        "*) exit 9 ;;\nesac\n"
        'printf "%s\\n" "$kind" >> "$TEST_CALLS"\n'
        'if [ "$TEST_FAILURE" = "$kind" ]; then\n'
        '  printf "private-endpoint-and-secret" >&2; exit 1\nfi\n'
        'if [ "$TEST_FAILURE" = "${kind}_limit" ]; then\n'
        '  printf \'{"status":"LIMIT_REACHED","checked":1}\\n\'; exit 1\nfi',
    }.items():
        tool = tools / name
        tool.write_text("#!/bin/sh\n" + body + "\n")
        tool.chmod(0o700)
    dump = tmp_path / "synthetic.dump"
    dump.write_bytes(b"synthetic")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    options = []
    if selected in {"artifacts", "both"}:
        options.extend(["--artifacts-max-items", "17"])
    if selected in {"credentials", "both"}:
        options.extend(["--credentials-max-items", "23"])
    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "verify-restore.sh"),
            "--dump",
            str(dump),
            "--database-url",
            "postgresql://localhost/source",
            "--manifest",
            str(manifest),
            "--isolated-dependencies",
            *options,
        ],
        env={
            "PATH": f"{tools}:{os.environ['PATH']}",
            "APP_ENV": "local",
            "DATABASE_URL": "postgresql://localhost/not_the_target",
            "RECOVERY_MANIFEST_HMAC_KEY": "synthetic-key-" * 4,
            "KEEP_RESTORE_DB": "1" if keep else "0",
            "TEST_FAILURE": failure,
            "TEST_CALLS": str(calls),
            "TEST_TARGET": str(target),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == (0 if failure == "none" else 1), result.stderr
    expected = ["created", "manifest", "research"]
    if selected in {"artifacts", "both"}:
        expected.append("artifacts")
    if selected in {"credentials", "both"} and not failure.startswith("artifacts"):
        expected.append("credentials")
    if failure == "none" and not keep:
        expected.append("dropped")
    assert calls.read_text().splitlines() == expected
    assert "synthetic-key" not in result.stdout + result.stderr
    assert "private-endpoint-and-secret" not in result.stdout + result.stderr

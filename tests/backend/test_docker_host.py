"""The deadline helper must not depend on mutable controller state to stop a guest."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from polycolab.execution import docker_host

ATTEMPT = "a" * 32


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> docker_host.Host:
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    (root / "attempts").mkdir()
    (root / "attempts" / f"{ATTEMPT}.json").write_text(
        json.dumps({"backend": "gvisor", "container": "polycolab-exec-" + ATTEMPT})
    )
    config = tmp_path / "host.json"
    config.write_text(
        json.dumps(
            {"state_dir": str(root), "executor_uid": os.getuid(), "docker_socket": "/test.sock"}
        )
    )
    read_json = docker_host.read_json

    def read(path: Path, uid: int) -> dict[str, Any]:
        if path == config:
            # The real entrypoint requires a root-owned config; tests need no sudo.
            assert uid == 0
            return read_json(path, os.getuid())
        return read_json(path, uid)

    monkeypatch.setattr(docker_host, "read_json", read)
    group = docker_host.Host.group

    def test_group(self: docker_host.Host, attempt: str) -> Path:
        return tmp_path / "cgroups" / group(self, attempt).name

    monkeypatch.setattr(docker_host.Host, "group", test_group)
    instance = docker_host.Host(config)
    target = instance.group(ATTEMPT)
    target.mkdir(parents=True)
    (target / "cgroup.kill").write_text("")
    (target / "cgroup.events").write_text("populated 0\n")
    return instance


def damage(host: docker_host.Host, kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    journal = host.root / "attempts" / f"{ATTEMPT}.json"
    if kind == "truncated":
        journal.write_text('{"backend":')
    elif kind == "missing":
        journal.unlink()
    elif kind == "unreadable":
        read_json = docker_host.read_json

        def read(path: Path, uid: int) -> dict[str, Any]:
            if path == journal:
                raise PermissionError("journal unavailable")
            return read_json(path, uid)

        monkeypatch.setattr(docker_host, "read_json", read)
    elif kind == "wrong_owner":
        fstat = os.fstat
        inode = journal.stat().st_ino

        def info(fd: int) -> os.stat_result:
            result = fstat(fd)
            if result.st_ino == inode:
                fields = list(result)
                fields[4] = host.uid + 1
                return os.stat_result(fields)
            return result

        monkeypatch.setattr(os, "fstat", info)
    elif kind == "state_missing":
        host.root.rename(host.root.with_name("unavailable-state"))
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("action", ["stop", "release"])
@pytest.mark.parametrize(
    "kind", ["truncated", "missing", "unreadable", "wrong_owner", "state_missing"]
)
def test_shutdown_ignores_journal_storage(
    host: docker_host.Host, kind: str, action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    damage(host, kind, monkeypatch)
    read_json = docker_host.read_json

    def config_only(path: Path, uid: int) -> dict[str, Any]:
        assert path == host.config_path, "shutdown must not read the journal"
        return read_json(path, uid)

    calls: list[tuple[str, ...]] = []

    def command(*args: str, **_: Any) -> bytes:
        assert (host.group(ATTEMPT) / "cgroup.kill").read_text() == "1"
        calls.append(args)
        return b""

    monkeypatch.setattr(docker_host, "read_json", config_only)
    monkeypatch.setattr(docker_host, "command", command)
    monkeypatch.setattr("sys.argv", ["helper", str(host.config_path), action, ATTEMPT])
    # Construct a fresh Host, just as the independent guard's ExecStopPost does.
    assert docker_host.main() == 0
    assert docker_host.main() == 0
    slice_name, guard, holder = host.names(ATTEMPT)
    expected: list[tuple[str, ...]] = [("systemctl", "stop", holder, slice_name)]
    if action == "release":
        expected += [("systemctl", "stop", guard), ("systemctl", "reset-failed", guard, holder)]
    assert calls == expected * 2


@pytest.mark.parametrize(
    "kind", ["truncated", "missing", "unreadable", "wrong_owner", "state_missing"]
)
@pytest.mark.parametrize("action", ["prepare", "verify"])
def test_admission_still_rejects_bad_storage(
    host: docker_host.Host, kind: str, action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    damage(host, kind, monkeypatch)
    # Isolate storage validation from the unrelated Linux/runsc preflight checks.
    monkeypatch.setattr(docker_host.Host, "check", docker_host.Host.check_state)
    with pytest.raises((OSError, ValueError)):
        getattr(host, action)(ATTEMPT)


@pytest.mark.parametrize("kind", ["missing", "permissions", "symlink"])
def test_preflight_rejects_invalid_state_directory(host: docker_host.Host, kind: str) -> None:
    if kind == "permissions":
        host.root.chmod(0o755)
    else:
        moved = host.root.with_name("moved")
        host.root.rename(moved)
        if kind == "symlink":
            host.root.symlink_to(moved, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        host.check()


@pytest.mark.parametrize("attempt", ["", "../" + ATTEMPT, "b" * 31, "A" * 32, ATTEMPT + ".slice"])
@pytest.mark.parametrize("action", ["stop", "release"])
def test_shutdown_rejects_invalid_identity(
    host: docker_host.Host, attempt: str, action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> bytes:
        pytest.fail("invalid identity must not invoke systemctl")

    monkeypatch.setattr(docker_host, "command", unexpected)
    with pytest.raises(ValueError, match="invalid attempt"):
        getattr(host, action)(attempt)
    assert (host.group(ATTEMPT) / "cgroup.kill").read_text() == ""


@pytest.mark.parametrize("action", ["stop", "release"])
def test_shutdown_requires_empty_cgroup(
    host: docker_host.Host, action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    (host.group(ATTEMPT) / "cgroup.events").write_text("populated 1\n")
    monkeypatch.setattr(docker_host, "command", lambda *args, **kwargs: b"")
    with pytest.raises(ValueError, match="termination unconfirmed"):
        getattr(host, action)(ATTEMPT)


def test_already_removed_cgroup_is_safe(
    host: docker_host.Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_host, "command", lambda *args, **kwargs: b"")
    host.release("b" * 32)
    host.release("b" * 32)


@pytest.mark.parametrize("action", ["stop", "release"])
def test_shutdown_still_requires_protected_configuration(
    host: docker_host.Host, action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    host.config_path.chmod(0o666)
    monkeypatch.setattr("sys.argv", ["helper", str(host.config_path), action, ATTEMPT])
    assert docker_host.main() == 1
    assert (host.group(ATTEMPT) / "cgroup.kill").read_text() == ""

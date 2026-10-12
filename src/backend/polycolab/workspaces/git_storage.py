"""Bounded bare Git adapter. No shell, hooks, credentials, or checkout of user files."""

from __future__ import annotations

import fcntl
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from polycolab.entities.repositories import RepositoryError

TRANSFER_LIMIT = 16 * 1024 * 1024
ZERO = "0" * 40


def path_name(value: str) -> str:
    if (
        not value
        or len(value.encode()) > 240
        or "\\" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or any(p in {"", ".", ".."} or p.casefold() == ".git" for p in value.split("/"))
    ):
        raise RepositoryError("repository_invalid_path", 422)
    return value


def branch_name(value: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}", value)
        or ".." in value
        or "//" in value
        or "@{" in value
        or any(part.startswith(".") or part.endswith((".", ".lock")) for part in value.split("/"))
        or value.endswith("/")
        or value == "HEAD"
    ):
        raise RepositoryError("repository_invalid_branch", 422)
    return value


def oid(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise RepositoryError("repository_invalid_commit", 422)
    return value


class GitRepository:
    def __init__(self, root: Path, workspace_id: UUID, quota: int = 64 * 1024 * 1024):
        self.root = root.resolve()
        self.path = self.root / f"{workspace_id}.git"
        self.quota = quota

    @contextmanager
    def locked(self, *, initialize: bool = True) -> Iterator[None]:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(
            self.root / f"{self.path.name}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RepositoryError("repository_busy", 409) from None
                    time.sleep(0.02)
            if self.path.is_symlink():
                raise RepositoryError("repository_unavailable", 503)
            if not initialize and (
                not (self.path / "HEAD").exists() or not self.head("main", missing=True)
            ):
                raise RepositoryError("repository_storage_missing", 503)
            if not (self.path / "HEAD").exists():
                self.path.mkdir(mode=0o700, exist_ok=True)
                self.git("init", "--bare", "--initial-branch=main", str(self.path))
            if not self.head("main", missing=True):
                tree = self.git("mktree", data=b"").decode().strip()
                commit = self.commit_tree(tree, [], "Initialize workspace", "Polycolab")
                self.advance("main", ZERO, commit)
            yield
        finally:
            os.close(fd)

    def git(
        self,
        *args: str,
        data: bytes | None = None,
        env: dict[str, str] | None = None,
        allowed: tuple[int, ...] = (0,),
        limit: int = TRANSFER_LIMIT,
    ) -> bytes:
        variables = {
            "PATH": os.defpath,
            "HOME": str(self.root),
            "LC_ALL": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_AUTHOR_NAME": "Polycolab",
            "GIT_AUTHOR_EMAIL": "workspace@polycolab.invalid",
            "GIT_COMMITTER_NAME": "Polycolab",
            "GIT_COMMITTER_EMAIL": "workspace@polycolab.invalid",
        }
        variables.update(env or {})
        command = [
            "git",
            "--git-dir",
            str(self.path),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.allow=never",
            "-c",
            "core.fsync=committed",
            "-c",
            "gc.auto=0",
            "-c",
            "maintenance.auto=false",
            "-c",
            "core.attributesFile=/dev/null",
            *args,
        ]
        try:
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("git_process.py")),
                        str(max(self.quota, TRANSFER_LIMIT)),
                        *command[1:],
                    ],
                    stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                    stdout=output,
                    stderr=errors,
                    env=variables,
                    start_new_session=True,
                )
                try:
                    process.communicate(data, timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
                if process.returncode not in allowed:
                    raise RepositoryError("repository_operation_failed", 409)
                if output.tell() > limit:
                    raise RepositoryError("repository_transfer_limit", 413)
                output.seek(0)
                return output.read(limit + 1)
        except OSError, subprocess.TimeoutExpired:
            raise RepositoryError("repository_unavailable", 503) from None

    def head(self, branch: str, *, missing: bool = False) -> str:
        value = (
            self.git(
                "show-ref",
                "--verify",
                "--hash",
                f"refs/heads/{branch_name(branch)}",
                allowed=(0, 1, 128) if missing else (0,),
            )
            .decode()
            .strip()
        )
        return value

    def accessible(self, commit: str) -> str:
        oid(commit)
        refs = self.git(
            "for-each-ref", f"--contains={commit}", "--format=%(refname)", "refs/heads/"
        )
        if not refs:
            raise RepositoryError("repository_commit_not_found", 404)
        return commit

    def branches(self) -> dict[str, str]:
        lines = (
            self.git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads/")
            .decode()
            .splitlines()
        )
        return dict(line.split(" ", 1) for line in lines)

    def entries(self, commit: str) -> dict[str, tuple[str, str, int]]:
        items = self.git("ls-tree", "-r", "-z", "-l", oid(commit)).split(b"\0")
        result: dict[str, tuple[str, str, int]] = {}
        total = 0
        for item in items:
            if not item:
                continue
            info, raw_path = item.split(b"\t", 1)
            mode, kind, digest, raw_size = info.decode().split()
            try:
                name = path_name(raw_path.decode("utf-8"))
            except UnicodeError:
                raise RepositoryError("repository_invalid_path", 422) from None
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise RepositoryError("repository_unsupported_file", 422)
            size = int(raw_size)
            total += size
            if len(result) >= 4096 or total > TRANSFER_LIMIT:
                raise RepositoryError("repository_transfer_limit", 413)
            result[name] = (mode, digest, size)
        return result

    def read(self, commit: str, path: str) -> bytes:
        item = self.entries(commit).get(path_name(path))
        if item is None:
            raise RepositoryError("repository_file_not_found", 404)
        return self.git("cat-file", "blob", item[1])

    def size(self) -> int:
        return sum(
            p.stat().st_size
            for root in (self.path, self.root / f"{self.path.stem}.worktrees")
            for p in root.rglob("*")
            if p.is_file() and not p.is_symlink()
        )

    def commit_tree(self, tree: str, parents: list[str], message: str, author: str) -> str:
        args = ["commit-tree", oid(tree)]
        for parent in parents:
            args += ["-p", oid(parent)]
        return (
            self.git(*args, data=(message + "\n").encode(), env={"GIT_AUTHOR_NAME": author})
            .decode()
            .strip()
        )

    def changed_tree(self, base: str, changes: dict[str, bytes | None]) -> str:
        entries = self.entries(base)
        added = sum(len(data) for data in changes.values() if data is not None)
        if added > TRANSFER_LIMIT or self.size() + added + 8192 > self.quota:
            raise RepositoryError("repository_quota_exceeded", 413)
        for name, content in changes.items():
            path_name(name)
            if content is None:
                if name not in entries:
                    raise RepositoryError("repository_file_not_found", 404)
                del entries[name]
            else:
                entries[name] = (entries.get(name, ("100644", "", 0))[0], "", len(content))
        if sum(item[2] for item in entries.values()) > TRANSFER_LIMIT or len(entries) > 4096:
            raise RepositoryError("repository_transfer_limit", 413)
        names = set(entries)
        for name in names:
            parts = name.split("/")
            if any("/".join(parts[:i]) in names for i in range(1, len(parts))):
                raise RepositoryError("repository_path_collision", 422)
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            env = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
            self.git("read-tree", base, env=env)
            records = bytearray()
            for name, content in changes.items():
                if content is None:
                    records.extend(f"0 {ZERO}\t{name}\0".encode())
                else:
                    digest = self.git("hash-object", "-w", "--stdin", data=content).decode().strip()
                    records.extend(f"{entries[name][0]} {digest}\t{name}\0".encode())
            self.git("update-index", "-z", "--index-info", data=bytes(records), env=env)
            return self.git("write-tree", env=env).decode().strip()

    def advance(self, branch: str, old: str, new: str) -> None:
        self.git("update-ref", f"refs/heads/{branch_name(branch)}", oid(new), oid(old))

    def contains(self, branch: str, commit: str) -> bool:
        return bool(
            self.git(
                "for-each-ref",
                f"--contains={oid(commit)}",
                "--format=%(refname)",
                f"refs/heads/{branch_name(branch)}",
            )
        )

    def history(self, commit: str, limit: int = 50) -> list[dict[str, str]]:
        hashes = self.git("rev-list", f"--max-count={limit}", oid(commit)).decode().splitlines()
        result = []
        for digest in hashes:
            parts = (
                self.git("show", "-s", "--format=%H%x00%an%x00%aI%x00%s", digest)
                .decode("utf-8", "replace")
                .strip()
                .split("\0", 3)
            )
            result.append(
                dict(zip(("commit", "author", "created_at", "message"), parts, strict=True))
            )
        return result

    def diff(self, base: str, target: str) -> str:
        return self.git(
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames", oid(base), oid(target), "--"
        ).decode("utf-8", "replace")

    def merge(self, target: str, source: str) -> tuple[str, list[str]]:
        raw = self.git(
            "merge-tree",
            "--write-tree",
            "--name-only",
            "-z",
            oid(target),
            oid(source),
            allowed=(0, 1),
        )
        items = raw.split(b"\0")
        tree = items[0].decode().strip()
        conflicts = []
        for item in items[1:]:
            if not item:
                break
            conflicts.append(path_name(item.decode()))
        return tree, conflicts

    def bundle(self, branch: str, *, commit: str | None = None) -> bytes:
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            path = Path(temporary) / "repository.bundle"
            ref = f"refs/heads/{branch_name(branch)}"
            if commit is not None:
                ref = "refs/polycolab-checkout/input"
                self.git("update-ref", ref, oid(commit))
            try:
                self.git("bundle", "create", str(path), ref)
            finally:
                if commit is not None:
                    self.git("update-ref", "-d", ref)
            if path.stat().st_size > TRANSFER_LIMIT:
                raise RepositoryError("repository_transfer_limit", 413)
            return path.read_bytes()

    def import_bundle(self, data: bytes, branch: str, expected: str) -> str:
        """Only validated objects cross from a disposable repository into canonical Git."""
        if len(data) > TRANSFER_LIMIT or self.size() + len(data) > self.quota:
            raise RepositoryError("repository_quota_exceeded", 413)
        from uuid import uuid4

        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            staging = GitRepository(Path(directory), uuid4(), self.quota)
            with staging.locked():
                bundle = Path(directory) / "input.bundle"
                bundle.write_bytes(data)
                heads = staging.git("bundle", "list-heads", str(bundle)).decode().splitlines()
                if len(heads) != 1:
                    raise RepositoryError("repository_invalid_bundle", 422)
                commit, ref = heads[0].split(" ", 1)
                if ref != f"refs/heads/{branch_name(branch)}":
                    raise RepositoryError("repository_invalid_bundle", 422)
                oid(commit)
                staging.git(
                    "-c",
                    "protocol.file.allow=always",
                    "fetch",
                    "--no-tags",
                    str(bundle),
                    f"+{ref}:{ref}",
                )
                staging.git("fsck", "--strict", "--no-reflogs", commit)
                staging.git("merge-base", "--is-ancestor", oid(expected), commit)
                # Validate every imported historical tree, not only its tip.
                commits = staging.git("rev-list", commit, f"^{expected}").decode().splitlines()
                if len(commits) > 256 or staging.size() > self.quota:
                    raise RepositoryError("repository_quota_exceeded", 413)
                for candidate in [commit, *commits]:
                    staging.entries(candidate)
                if self.size() + staging.size() > self.quota:
                    raise RepositoryError("repository_quota_exceeded", 413)
                self.git(
                    "-c",
                    "protocol.file.allow=always",
                    "fetch",
                    "--no-tags",
                    "--no-write-fetch-head",
                    str(staging.path),
                    ref,
                )
                return commit

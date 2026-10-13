"""Managed linked checkouts and durable, replayable saved-file snapshots.

All operations require the parent repository lock. A fsynced journal is the
linearization point: recovery finishes only operations already authorized there.
Snapshots are private refs, never commits on the user's branch.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from polycolab.entities.repositories import RepositoryError
from polycolab.projects.git_storage import GitRepository, branch_name, oid


class WorktreeStorage:
    def __init__(self, git: GitRepository):
        self.git = git
        self.root = git.root / f"{git.path.stem}.worktrees"
        self.journal = git.path / "polycolab-operation.json"

    def path(self, identifier: UUID) -> Path:
        return self.root / str(identifier)

    def ref(self, identifier: UUID) -> str:
        return f"refs/polycolab/worktrees/{identifier}"

    def revision(self, identifier: UUID) -> str:
        return self.git.git("rev-parse", "--verify", self.ref(identifier)).decode().strip()

    def exists(self, identifier: UUID) -> bool:
        return bool(self.git.git("for-each-ref", "--format=%(objectname)", self.ref(identifier)))

    def inventory(self) -> dict[str, str]:
        result = {}
        for record in self.git.git("worktree", "list", "--porcelain", "-z").split(b"\0\0"):
            fields = dict(
                part.decode().split(" ", 1) for part in record.split(b"\0") if b" " in part
            )
            if "branch" in fields:
                result[fields["worktree"]] = fields["branch"].removeprefix("refs/heads/")
        return result

    def available(self, identifier: UUID, branch: str) -> bool:
        path = self.path(identifier)
        return (
            not self.root.is_symlink()
            and not (path / ".git").is_symlink()
            and not path.is_symlink()
            and (path / ".git").is_file()
            and self.inventory().get(str(path)) == branch
        )

    def snapshot(self, identifier: UUID, tree: str, head: str, previous: str | None) -> str:
        return self.git.commit_tree(
            tree,
            [previous, head] if previous and previous != head else [head],
            json.dumps({"head": head, "operation": str(uuid4())}),
            "Polycolab saved state",
        )

    def ignored_files(self, identifier: UUID) -> set[str]:
        """Use the checkout's HEAD index and ignore rules; tracked files stay visible."""
        path = self.path(identifier)
        output = self.git.git(
            "--git-dir",
            str(path / ".git"),
            "--work-tree",
            str(path),
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        )
        return {name.decode() for name in output.split(b"\0") if name}

    def snapshot_head(self, revision: str) -> str:
        message = self.git.git("show", "-s", "--format=%B", oid(revision)).decode()
        return oid(json.loads(message)["head"])

    @staticmethod
    def sync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def durable_json(self, path: Path, value: dict[str, str]) -> None:
        temporary = path.with_suffix(".tmp")
        with temporary.open("w") as file:
            json.dump(value, file)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        self.sync_directory(path.parent)

    def apply(self, identifier: UUID, branch: str, revision: str, *, create: bool = False) -> None:
        """Call only after final authorization and a committed SQL receipt."""
        if self.root.is_symlink() or self.path(identifier).is_symlink():
            raise RepositoryError("worktree_unavailable", 503)
        head = self.snapshot_head(revision)
        entries = self.git.entries(revision)
        if self.git.size() + sum(item[2] for item in entries.values()) > self.git.quota:
            raise RepositoryError("repository_quota_exceeded", 413)
        self.durable_json(
            self.journal,
            {
                "id": str(identifier),
                "branch": branch_name(branch),
                "revision": oid(revision),
                "old_head": self.git.head(branch),
                "head": head,
                "create": str(create),
            },
        )
        self.recover()

    def recover(self) -> None:
        if not self.journal.exists():
            return
        value = json.loads(self.journal.read_text())
        identifier = UUID(value["id"])
        branch, revision, head = value["branch"], value["revision"], value["head"]
        path = self.path(identifier)
        if not self.available(identifier, branch):
            if value["create"] != "True":
                raise RepositoryError("worktree_unavailable", 503)
            self.root.mkdir(mode=0o700, exist_ok=True)
            # Only our generated path can be restored; never prune someone else's checkout.
            if str(path) in self.inventory():
                self.git.git("worktree", "remove", "--force", str(path))
            self.git.git("worktree", "add", str(path), branch)
        current = self.git.head(branch)
        if current != head:
            if current != value["old_head"]:
                raise RepositoryError("worktree_recovery_conflict", 503)
            self.git.advance(branch, current, head)
        self.git.git("update-ref", self.ref(identifier), oid(revision))
        self.materialize(identifier, revision, head)
        self.journal.unlink()
        self.sync_directory(self.git.path)

    def materialize(self, identifier: UUID, revision: str, head: str) -> None:
        path = self.path(identifier)
        # These directories are service-owned and never mounted into a guest.
        # Rebuild the complete saved snapshot, including deletion and file/directory swaps.
        for child in path.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for name, (mode, blob, _) in self.git.entries(revision).items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as file:
                file.write(self.git.git("cat-file", "blob", blob))
                file.flush()
                os.fchmod(file.fileno(), 0o755 if mode == "100755" else 0o644)
                os.fsync(file.fileno())
        link = (path / ".git").read_text().strip().removeprefix("gitdir: ")
        gitdir = Path(link).resolve()
        if not gitdir.is_relative_to(self.git.path / "worktrees"):
            raise RepositoryError("worktree_unavailable", 503)
        self.git.git("read-tree", head, env={"GIT_INDEX_FILE": str(gitdir / "index")})
        for directory, _, _ in os.walk(path, topdown=False):
            self.sync_directory(Path(directory))

    def initialize(self, identifier: UUID, branch: str) -> None:
        if self.exists(identifier):
            return
        head = self.git.head(branch)
        tree = self.git.git("rev-parse", f"{head}^{{tree}}").decode().strip()
        revision = self.snapshot(identifier, tree, head, None)
        self.apply(identifier, branch, revision, create=True)

    def clean(self, identifier: UUID, branch: str) -> bool:
        return self.git.entries(self.git.head(branch)) == self.git.entries(
            self.revision(identifier)
        )

    def remove(self, identifier: UUID, branch: str) -> None:
        if self.available(identifier, branch):
            self.git.git("worktree", "remove", "--force", str(self.path(identifier)))

    def restore(self, identifier: UUID, branch: str) -> None:
        head = self.git.head(branch)
        tree = self.git.git("rev-parse", f"{head}^{{tree}}").decode().strip()
        revision = self.snapshot(
            identifier, tree, head, self.revision(identifier) if self.exists(identifier) else None
        )
        self.apply(identifier, branch, revision, create=True)

    def contains(self, identifier: UUID, revision: str) -> bool:
        return bool(
            self.git.git(
                "for-each-ref",
                f"--contains={oid(revision)}",
                "--format=%(refname)",
                self.ref(identifier),
            )
        )

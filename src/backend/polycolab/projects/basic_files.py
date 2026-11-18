"""Current project files on the server volume, without retained revisions."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.access.authorization import ProjectAction, lock_project_authorization, project_policy
from polycolab.entities.repositories import RepositoryError
from polycolab.projects.git_storage import path_name
from polycolab.projects.repository_schemas import RepositoryModel
from polycolab.transaction import Transaction

FILE_LIMIT = 700_000
FILE_COUNT = 2000


class BasicFileCommand(RepositoryModel):
    action: Literal["list", "read", "write", "rename", "delete"]
    path: str = Field(default="", max_length=240)
    destination: str | None = Field(default=None, max_length=240)
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content: str | None = Field(default=None, max_length=FILE_LIMIT)
    content_base64: str | None = Field(default=None, max_length=1_000_000)

    @model_validator(mode="after")
    def validate_command(self) -> BasicFileCommand:
        if self.action != "list":
            path_name(self.path)
        if self.action == "rename":
            if self.destination is None:
                raise ValueError("destination is required")
            path_name(self.destination)
        if self.action in {"rename", "delete"} and self.expected_digest is None:
            raise ValueError("expected_digest is required")
        if self.action == "write" and (self.content is None) == (self.content_base64 is None):
            raise ValueError("provide content or content_base64")
        return self


class BasicFileRead(RepositoryModel):
    path: str
    size: int
    digest: str
    binary: bool
    content_base64: str | None = None
    content: str | None = None


class BasicFilesRead(RepositoryModel):
    files: list[BasicFileRead]
    writable: bool


class BasicFiles:
    def __init__(self, tx: Transaction, root: Path, project_id: UUID, user_id: UUID, quota: int):
        self.tx, self.project_id, self.user_id = tx, project_id, user_id
        self.root = root.resolve()
        self.directory = self.root / f"{project_id}.files"
        self.quota = quota
        self.authorize_access: Callable[[bool], None] | None = None

    @contextmanager
    def locked(self, write: bool) -> Iterator[None]:
        if write or self.authorize_access is not None:
            lock_project_authorization(self.tx, project_id=self.project_id, user_id=self.user_id)
        access = project_policy.require_scope(
            self.tx,
            self.project_id,
            self.user_id,
            ProjectAction.WRITE_FILES if write else ProjectAction.VIEW,
        )
        if access.project.file_mode != "basic":
            raise RepositoryError("basic_mode_required", 409)
        if write and access.project.archived_at:
            raise RepositoryError("project_archived", 409)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            self.root / f"{self.project_id}.files.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
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
            if self.authorize_access is not None:
                self.authorize_access(write)
            if self.directory.is_symlink():
                raise RepositoryError("repository_invalid_path", 422)
            self.directory.mkdir(exist_ok=True, mode=0o700)
            yield
        finally:
            os.close(fd)

    def path(self, name: str) -> Path:
        target = self.directory / path_name(name)
        current = self.directory
        for part in target.relative_to(self.directory).parts:
            current /= part
            if current.is_symlink():
                raise RepositoryError("repository_invalid_path", 422)
            if current != target and current.exists() and not current.is_dir():
                raise RepositoryError("file_path_conflict", 409)
        if target.exists() and not target.is_file():
            raise RepositoryError("file_path_conflict", 409)
        return target

    def read(self, target: Path, contents: bool = False) -> BasicFileRead:
        if not target.is_file():
            raise RepositoryError("file_not_found", 404)
        if target.stat().st_size > FILE_LIMIT:
            raise RepositoryError("repository_transfer_limit", 413)
        data = target.read_bytes()
        try:
            text = data.decode("utf-8") if b"\0" not in data else None
        except UnicodeDecodeError:
            text = None
        return BasicFileRead(
            path=target.relative_to(self.directory).as_posix(),
            size=len(data),
            digest=hashlib.sha256(data).hexdigest(),
            binary=text is None,
            content_base64=base64.b64encode(data).decode() if contents else None,
            content=text if contents else None,
        )

    def listing(self) -> BasicFilesRead:
        files = []
        for target in sorted(self.directory.rglob("*")):
            if target.is_symlink():
                raise RepositoryError("repository_invalid_path", 422)
            if target.is_file():
                files.append(self.read(self.path(target.relative_to(self.directory).as_posix())))
                if len(files) > FILE_COUNT:
                    raise RepositoryError("repository_quota_exceeded", 413)
        return BasicFilesRead(
            files=files,
            writable=project_policy.can(
                self.tx,
                self.project_id,
                self.user_id,
                ProjectAction.WRITE_FILES,
            ),
        )

    @staticmethod
    def sync_directory(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def sync_parents(self, path: Path) -> None:
        while path != self.root:
            self.sync_directory(path)
            path = path.parent
        self.sync_directory(self.root)

    def execute(self, command: BasicFileCommand) -> BasicFilesRead | BasicFileRead:
        with self.locked(command.action not in {"list", "read"}):
            if command.action == "list":
                return self.listing()
            target = self.path(command.path)
            if command.action == "read":
                value = self.read(target, True)
                if command.expected_digest is not None and command.expected_digest != value.digest:
                    raise RepositoryError("file_changed", 409)
                return value
            current = self.read(target) if target.exists() else None
            if (current.digest if current else None) != command.expected_digest:
                raise RepositoryError("file_changed", 409)
            if command.action == "write":
                try:
                    data = (
                        command.content.encode()
                        if command.content is not None
                        else base64.b64decode(command.content_base64 or "", validate=True)
                    )
                except ValueError:
                    raise RepositoryError("invalid_file_bytes", 422) from None
                if len(data) > FILE_LIMIT:
                    raise RepositoryError("repository_transfer_limit", 413)
                listing = self.listing()
                if sum(f.size for f in listing.files) - (current.size if current else 0) + len(
                    data
                ) > self.quota or (current is None and len(listing.files) >= FILE_COUNT):
                    raise RepositoryError("repository_quota_exceeded", 413)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Stage outside the project so interrupted writes never appear as user files.
                with tempfile.NamedTemporaryFile(
                    dir=self.root, prefix=".file-write-", delete=False
                ) as staged:
                    temporary = Path(staged.name)
                    try:
                        staged.write(data)
                        staged.flush()
                        os.fsync(staged.fileno())
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                self.sync_parents(target.parent)
                return self.read(target, True)
            if current is None:
                raise RepositoryError("file_not_found", 404)
            if command.action == "rename":
                destination = self.path(command.destination or "")
                if destination.exists():
                    raise RepositoryError("file_exists", 409)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.rename(destination)
                self.sync_parents(destination.parent)
                self.sync_parents(target.parent)
                return self.read(destination, True)
            target.unlink()
            self.sync_parents(target.parent)
            return self.listing()

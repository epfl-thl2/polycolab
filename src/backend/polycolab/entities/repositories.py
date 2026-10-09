"""Application values for workspace Git history."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class RepositoryError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True)
class RepositoryReceipt:
    id: UUID
    workspace_id: UUID
    user_id: UUID
    key: str
    digest: str
    branch: str
    old_commit: str
    new_commit: str
    completed: bool
    created_at: datetime


@dataclass(frozen=True)
class RepositorySession:
    session_id: UUID
    workspace_id: UUID
    owner_id: UUID
    enabled: bool
    active: bool
    branch: str | None = None


@dataclass(frozen=True)
class RepositoryRun:
    run_id: UUID
    session_id: UUID
    input_commit: str
    output_commit: str | None
    branch: str | None = None


@dataclass(frozen=True)
class WorkspaceTask:
    id: UUID
    workspace_id: UUID
    title: str
    branch: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

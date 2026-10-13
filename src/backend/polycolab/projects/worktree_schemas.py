"""Native Git worktree HTTP contracts."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from polycolab.projects.git_storage import branch_name, oid
from polycolab.projects.repository_schemas import (
    RepositoryEntry,
    RepositoryFileChange,
    RepositoryModel,
)
from polycolab.projects.task_schemas import ProjectTaskRead


class WorktreeChange(RepositoryModel):
    path: str
    status: Literal["added", "modified", "deleted"]


class WorktreeRead(ProjectTaskRead):
    head_commit: str
    revision: str | None
    lifecycle: Literal["active", "removed", "unavailable"]
    writable: bool
    files: list[RepositoryEntry]
    ignored_files: list[str] = Field(default_factory=list)
    changed_files: list[WorktreeChange]


class WorktreeCreate(RepositoryModel):
    client_request_id: UUID
    title: str = Field(min_length=1, max_length=300)
    branch: str
    start_branch: str = "main"
    _branch = field_validator("branch", "start_branch")(branch_name)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class WorktreeRevision(RepositoryModel):
    expected_revision: str
    _revision = field_validator("expected_revision")(oid)


class WorktreeSave(WorktreeRevision):
    changes: list[RepositoryFileChange] = Field(min_length=1, max_length=256)


class WorktreeCommit(WorktreeRevision):
    message: str = Field(min_length=1, max_length=2000)


class WorktreeRemove(WorktreeRevision):
    discard_changes: bool = False


class WorktreeSaved(RepositoryModel):
    revision: str

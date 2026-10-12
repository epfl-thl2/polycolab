"""Browser contracts for member-only working files."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from polycolab.workspaces.git_storage import branch_name, oid, path_name


class RepositoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepositoryFileChange(RepositoryModel):
    path: str = Field(min_length=1, max_length=240)
    content_base64: str | None = Field(default=None, max_length=1_000_000)
    _path = field_validator("path")(path_name)


class RepositorySave(RepositoryModel):
    branch: str = "main"
    expected_commit: str
    changes: list[RepositoryFileChange] = Field(min_length=1, max_length=256)
    _branch = field_validator("branch")(branch_name)
    _commit = field_validator("expected_commit")(oid)


class RepositoryMerge(RepositoryModel):
    expected_target_revision: str | None = None
    expected_source_revision: str | None = None
    target: str = "main"
    source: str
    expected_target: str
    expected_source: str
    resolutions: list[RepositoryFileChange] | None = Field(default=None, max_length=256)
    _branches = field_validator("target", "source")(branch_name)
    _commits = field_validator("expected_target", "expected_source")(oid)


class RepositoryEntry(RepositoryModel):
    path: str
    size: int
    executable: bool


class RepositoryState(RepositoryModel):
    enabled: bool
    branch: str
    commit: str | None = None
    branches: dict[str, str] = Field(default_factory=dict)
    files: list[RepositoryEntry] = Field(default_factory=list)
    writable: bool = False


class RepositoryFile(RepositoryModel):
    commit: str
    path: str
    content_base64: str


class RepositoryCommit(RepositoryModel):
    commit: str
    author: str
    created_at: str
    message: str


class RepositorySaved(RepositoryModel):
    commit: str


class RepositoryConflictFile(RepositoryModel):
    path: str
    base_base64: str | None
    current_base64: str | None
    incoming_base64: str | None


class RepositoryMergePreview(RepositoryModel):
    target_revision: str | None = None
    source_revision: str | None = None
    target_commit: str
    source_commit: str
    diff: str
    conflicts: list[RepositoryConflictFile]


class RepositorySessionState(RepositoryModel):
    enabled: bool
    branch: str | None = None


class RepositoryRunState(RepositoryModel):
    worktree_id: UUID | None = None
    input_revision: str | None = None
    output_revision: str | None = None
    input_commit: str | None = None
    output_commit: str | None = None

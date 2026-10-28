"""Immutable application values for private worktree document builds."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

Engine = Literal["pdflatex", "lualatex"]
BuildStatus = Literal[
    "preparing", "queued", "running", "succeeded", "failed", "timed_out", "cancelled"
]
OutputKind = Literal["pdf", "log"]
ACTIVE = ("preparing", "queued", "running")


class BuildError(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class BuildBlob:
    key: str
    sha256: str
    byte_length: int
    verified: bool = False


@dataclass(frozen=True)
class DocumentBuild:
    id: UUID
    project_id: UUID
    worktree_id: UUID
    requested_by: UUID
    request_key: str
    revision: str
    main_file: str
    engine: Engine
    image: str
    status: BuildStatus
    created_at: datetime
    expires_at: datetime
    input: BuildBlob
    outputs: dict[str, BuildBlob]
    generation: UUID | None = None
    worker_id: str | None = None
    lease_until: datetime | None = None
    deadline: datetime | None = None
    physical_until: datetime | None = None
    error: str | None = None


@dataclass(frozen=True)
class BuildLimits:
    capacity: int = 2
    project_queue: int = 10
    project_bytes: int = 256 * 1024 * 1024
    execution_seconds: int = 120
    queue_seconds: int = 300
    retention_days: int = 30

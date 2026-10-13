"""Collaborative filesystem state, independent of transports and SQL."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class LinearFile:
    id: UUID
    path: str
    content: bytes
    document: bytes | None
    executable: bool = False
    deleted: bool = False


@dataclass(frozen=True)
class LinearState:
    project_id: UUID
    epoch: int = 1
    sequence: int = 0
    stored_bytes: int = 0
    files: tuple[LinearFile, ...] = ()


@dataclass(frozen=True)
class LinearOperation:
    project_id: UUID
    sequence: int
    epoch: int
    user_id: UUID
    key: str
    digest: str
    kind: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class LinearCheckpoint:
    id: UUID
    project_id: UUID
    sequence: int
    epoch: int
    title: str
    tree: str
    files: list[dict[str, Any]]
    created_at: datetime


@dataclass(frozen=True)
class LinearBatch:
    id: UUID
    project_id: UUID
    user_id: UUID
    run_id: UUID | None
    epoch: int
    base_sequence: int
    status: str
    changes: list[dict[str, Any]]
    conflicts: list[str] = field(default_factory=list)

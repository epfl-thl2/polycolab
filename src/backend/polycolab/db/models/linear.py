"""Durable collaborative documents, operations, checkpoints, and private AI batches."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlLinearWorkspace(Base):
    __tablename__ = "linear_workspaces"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    stored_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class SqlLinearFile(Base):
    __tablename__ = "linear_files"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("linear_workspaces.project_id"), index=True)
    path: Mapped[str] = mapped_column(String(1024))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    document: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    executable: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class SqlLinearOperation(Base):
    __tablename__ = "linear_operations"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "user_id", "request_key", name="uq_linear_operation_request"
        ),
    )
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("linear_workspaces.project_id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(200))
    digest: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlLinearCheckpoint(Base):
    __tablename__ = "linear_checkpoints"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("linear_workspaces.project_id"), index=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    epoch: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    tree: Mapped[str] = mapped_column(String(40))
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlLinearBatch(Base):
    __tablename__ = "linear_batches"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("linear_workspaces.project_id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id"), nullable=True, unique=True
    )
    epoch: Mapped[int] = mapped_column(Integer)
    base_sequence: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(32))
    digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    conflicts: Mapped[list[str]] = mapped_column(JSON, default=list)


class SqlLinearRun(Base):
    __tablename__ = "linear_runs"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("linear_workspaces.project_id"), index=True)
    epoch: Mapped[int] = mapped_column(Integer)
    original_checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("linear_checkpoints.id"))
    current_checkpoint_id: Mapped[UUID] = mapped_column(ForeignKey("linear_checkpoints.id"))
    refresh_generation: Mapped[int] = mapped_column(Integer, default=0)
    refresh_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    applied_sequence: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class SqlLinearConversion(Base):
    __tablename__ = "linear_conversions"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    source_worktree_id: Mapped[UUID] = mapped_column(ForeignKey("project_tasks.id"))
    source_revision: Mapped[str] = mapped_column(String(40))
    request_key: Mapped[str] = mapped_column(String(200))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)

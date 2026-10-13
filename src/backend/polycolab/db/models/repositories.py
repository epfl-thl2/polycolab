"""Project repository lifecycle and recoverable Git operation receipts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlProjectRepository(Base):
    __tablename__ = "project_repositories"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    native_worktrees: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRepositoryMutation(Base):
    __tablename__ = "repository_mutations"
    __table_args__ = (UniqueConstraint("project_id", "user_id", "key", name="uq_repository_retry"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_repositories.project_id"), index=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(200))
    digest: Mapped[str] = mapped_column(String(64))
    branch: Mapped[str] = mapped_column(String(100))
    old_commit: Mapped[str] = mapped_column(String(40))
    new_commit: Mapped[str] = mapped_column(String(40))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRepositorySession(Base):
    __tablename__ = "repository_sessions"
    session_id: Mapped[UUID] = mapped_column(ForeignKey("agent_sessions.id"), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_repositories.project_id"), index=True
    )
    base_commit: Mapped[str] = mapped_column(String(40))


class SqlRepositoryRun(Base):
    __tablename__ = "repository_runs"
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("repository_sessions.session_id"))
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_revision: Mapped[str | None] = mapped_column(String(40), nullable=True)
    worktree_id: Mapped[UUID | None] = mapped_column(ForeignKey("project_tasks.id"), nullable=True)
    input_commit: Mapped[str] = mapped_column(String(40))
    output_commit: Mapped[str | None] = mapped_column(String(40), nullable=True)

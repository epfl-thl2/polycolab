"""Durable member-visible tasks and their saved working copies."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlWorkspaceTask(Base):
    __tablename__ = "workspace_tasks"
    __table_args__ = (UniqueConstraint("workspace_id", "branch", name="uq_workspace_task_branch"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    branch: Mapped[str] = mapped_column(String(100))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

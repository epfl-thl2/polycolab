"""Build state belongs to projects and worktrees, never public research."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base


class SqlDocumentBuildQueue(Base):
    __tablename__ = "document_build_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    ready_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image: Mapped[str | None] = mapped_column(String(300))


class SqlDocumentBuild(Base):
    __tablename__ = "document_builds"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "worktree_id",
            "requested_by",
            "request_key",
            name="uq_document_build_retry",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    worktree_id: Mapped[UUID] = mapped_column(ForeignKey("project_tasks.id"), index=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_key: Mapped[str] = mapped_column(String(200))
    revision: Mapped[str] = mapped_column(String(64))
    main_file: Mapped[str] = mapped_column(String(1000))
    engine: Mapped[str] = mapped_column(String(20))
    image: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    input: Mapped[dict[str, object]] = mapped_column(JSON)
    outputs: Mapped[dict[str, dict[str, object]]] = mapped_column(JSON)
    generation: Mapped[UUID | None] = mapped_column()
    worker_id: Mapped[str | None] = mapped_column(String(200))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    physical_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(100))

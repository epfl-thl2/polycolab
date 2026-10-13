"""Persistence for drafts, immutable releases, and moderation decisions."""

from datetime import datetime
from uuid import UUID, uuid7

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlAgentLibraryEntry(Base):
    __tablename__ = "agent_library_entries"
    __table_args__ = (
        CheckConstraint("kind IN ('PROMPT','SKILL','PLUGIN')", name="ck_agent_library_kind"),
        CheckConstraint("revision > 0", name="ck_agent_library_revision"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    published_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "agent_library_versions.id",
            use_alter=True,
            ondelete="SET NULL",
            name="fk_agent_library_published",
        ),
        nullable=True,
    )
    source_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "agent_library_versions.id",
            use_alter=True,
            ondelete="SET NULL",
            name="fk_agent_library_source",
        ),
        nullable=True,
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAgentLibraryDraft(Base):
    __tablename__ = "agent_library_drafts"
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("agent_library_entries.id"), primary_key=True)
    content: Mapped[dict[str, object]] = mapped_column(JSON)


class SqlAgentLibraryVersion(Base):
    __tablename__ = "agent_library_versions"
    __table_args__ = (UniqueConstraint("entry_id", "number", name="uq_agent_library_version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("agent_library_entries.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, object]] = mapped_column(JSON)
    author_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    author_name: Mapped[str] = mapped_column(String(300))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAgentLibraryModeration(Base):
    __tablename__ = "agent_library_moderation"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid7)
    entry_id: Mapped[UUID] = mapped_column(ForeignKey("agent_library_entries.id"), index=True)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    hidden: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

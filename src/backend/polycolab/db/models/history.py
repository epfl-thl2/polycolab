"""Stable external actors and durable research activity, independent of execution."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
    event,
    update,
)
from sqlalchemy.engine import Connection
from sqlalchemy.engine.default import DefaultExecutionContext
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now

submission_counter = Table(
    "research_submission_counter",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("value", BigInteger, nullable=False),
    CheckConstraint("id = 1", name="ck_submission_counter_singleton"),
    CheckConstraint("value >= 0", name="ck_submission_counter_nonnegative"),
)


@event.listens_for(submission_counter, "after_create")
def initialize_submission_counter(target: Table, connection: Connection, **_: Any) -> None:
    connection.execute(target.insert().values(id=1, value=0))


def next_submission_number(context: DefaultExecutionContext) -> int:
    # UPDATE takes a row lock, so concurrent writers cannot allocate the same number.
    return int(
        context.connection.execute(
            update(submission_counter)
            .where(submission_counter.c.id == 1)
            .values(value=submission_counter.c.value + 1)
            .returning(submission_counter.c.value)
        ).scalar_one()
    )


class SqlExternalAgentIdentity(Base):
    __tablename__ = "external_agent_identities"
    __table_args__ = (
        UniqueConstraint("id", "sponsor_user_id", name="uq_external_identity_sponsor"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlResearchActivityEvent(Base):
    """Append-only source references; readable text is projected with live authorization."""

    __tablename__ = "research_activity_events"
    __table_args__ = (
        UniqueConstraint("source_kind", "source_id", name="uq_research_activity_source"),
        Index("ix_research_activity_time", "occurred_at", "id"),
        UniqueConstraint("submission_number", name="uq_research_activity_events_submission_number"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_number: Mapped[int] = mapped_column(
        BigInteger, default=next_submission_number, nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(64))
    source_id: Mapped[UUID] = mapped_column()
    contribution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("contribution_envelopes.id"), index=True
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_agent_identities.id"), index=True
    )
    sponsor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    ownership_scope_id: Mapped[UUID] = mapped_column(ForeignKey("research_scopes.id"), index=True)
    object_id: Mapped[UUID | None] = mapped_column(ForeignKey("research_objects.id"), index=True)
    revision_id: Mapped[UUID | None] = mapped_column(ForeignKey("object_revisions.id"), index=True)
    previous_revision_id: Mapped[UUID | None] = mapped_column(ForeignKey("object_revisions.id"))
    action: Mapped[str] = mapped_column(String(64))
    reconstructed: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

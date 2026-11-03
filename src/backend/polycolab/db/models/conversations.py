"""Read-only historical execution accounting for retired direct-provider sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base


class SqlLegacyConversationExecution(Base):
    __tablename__ = "legacy_conversation_executions"
    __table_args__ = (
        UniqueConstraint("conversation_id", "request_id", name="uq_legacy_execution_request"),
        UniqueConstraint("conversation_id", "sequence", name="uq_legacy_execution_sequence"),
        CheckConstraint(
            "status IN ('completed', 'failed', 'interrupted')", name="ck_legacy_execution_status"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    request_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("gateway_profiles.id"))
    model_id: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    reserved_cost_microusd: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

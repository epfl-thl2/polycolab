"""SQLAlchemy entities owned by the platform capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    IdempotencyRecordStatus,
)
from polycolab.entities.time import utc_now


class SqlIdempotencyRecord(Base):
    """Durable idempotency result for top-level canonical mutations."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "actor_key", "operation", "idempotency_key_digest", name="uq_idempotency_records_key"
        ),
        CheckConstraint("status IN ('COMMITTED', 'FAILED')", name="ck_idempotency_records_status"),
        CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_digest) = 64",
            name="ck_idempotency_records_digest_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_key: Mapped[str] = mapped_column(String(200), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    idempotency_key_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[IdempotencyRecordStatus] = mapped_column(
        Enum(IdempotencyRecordStatus, native_enum=False, length=16)
    )
    resource_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlIdempotencyRecord",
]

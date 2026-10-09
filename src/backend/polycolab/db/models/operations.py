"""SQLAlchemy entities owned by the operations capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlOperatorAccountRecovery(Base):
    """Content-free evidence for one privileged prototype account recovery."""

    __tablename__ = "operator_account_recoveries"
    __table_args__ = (
        CheckConstraint(
            "length(verification_reference_digest) = 64",
            name="ck_operator_account_recovery_reference",
        ),
        CheckConstraint(
            "revoked_session_count >= 0 AND revoked_credential_count >= 0 "
            "AND revoked_run_count >= 0",
            name="ck_operator_account_recovery_counts",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    verification_reference_digest: Mapped[str] = mapped_column(String(64))
    revoked_session_count: Mapped[int] = mapped_column(Integer)
    revoked_credential_count: Mapped[int] = mapped_column(Integer)
    revoked_run_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlOperatorRestoreInvalidation(Base):
    """Content-free evidence that one restored protected-access cohort was revoked."""

    __tablename__ = "operator_restore_invalidations"
    __table_args__ = (
        CheckConstraint(
            "length(recovery_reference_digest) = 64",
            name="ck_operator_restore_invalidation_reference",
        ),
        CheckConstraint(
            "revoked_session_count >= 0 AND revoked_credential_count >= 0 "
            "AND revoked_run_count >= 0",
            name="ck_operator_restore_invalidation_counts",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    recovery_reference_digest: Mapped[str] = mapped_column(String(64))
    revoked_session_count: Mapped[int] = mapped_column(Integer)
    revoked_credential_count: Mapped[int] = mapped_column(Integer)
    revoked_run_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlOperatorAccountRecovery",
    "SqlOperatorRestoreInvalidation",
]

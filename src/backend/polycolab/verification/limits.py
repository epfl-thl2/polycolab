"""Conservative verification accounting, serialized after project authorization.

All attempts are charged up front. Released reservations still count against a
rolling 24-hour budget. Lost/cancelled work retains capacity until its admitted
wall-time bound has elapsed; a lease timeout is not evidence of process death.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlVerificationJob, SqlVerificationReservation
from polycolab.entities.enums import VerificationJobState
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.platform.mutation_keys import lock_key
from polycolab.verification.contracts import ResourceLimits


class QuotaExceeded(Exception):
    pass


def lock_capacity(session: Session) -> None:
    # One short global capacity lock also makes the configured global queue cap
    # exact. Never acquire project/scope locks after this lock.
    lock_key(session, "verification", "capacity", "v1")


def admit(
    session: Session, *, user_id: UUID, scope_id: UUID, limits: ResourceLimits, settings: Settings
) -> None:
    now = utc_now()
    pending = (
        session.scalar(
            select(func.count())
            .select_from(SqlVerificationJob)
            .where(
                SqlVerificationJob.state.in_(
                    [VerificationJobState.QUEUED, VerificationJobState.RUNNING]
                )
            )
        )
        or 0
    )
    if pending >= settings.verification_queue_capacity:
        raise QuotaExceeded("verification_queue_full")
    for column, identity, concurrency, cpu, memory in (
        (
            SqlVerificationReservation.sponsor_user_id,
            user_id,
            settings.verification_user_concurrent_jobs,
            settings.verification_user_daily_cpu_seconds,
            settings.verification_user_daily_memory_byte_seconds,
        ),
        (
            SqlVerificationReservation.ownership_scope_id,
            scope_id,
            settings.verification_project_concurrent_jobs,
            settings.verification_project_daily_cpu_seconds,
            settings.verification_project_daily_memory_byte_seconds,
        ),
    ):
        active = (
            session.scalar(
                select(func.count())
                .select_from(SqlVerificationReservation)
                .where(
                    column == identity,
                    or_(
                        SqlVerificationReservation.accounted_at.is_(None),
                        SqlVerificationReservation.accounted_at > now,
                    ),
                )
            )
            or 0
        )
        used_cpu, used_memory = session.execute(
            select(
                func.coalesce(func.sum(SqlVerificationReservation.cpu_seconds), 0),
                func.coalesce(func.sum(SqlVerificationReservation.memory_byte_seconds), 0),
            ).where(
                column == identity,
                or_(
                    SqlVerificationReservation.admitted_at >= now - timedelta(days=1),
                    SqlVerificationReservation.accounted_at.is_(None),
                    SqlVerificationReservation.accounted_at > now,
                ),
            )
        ).one()
        if (
            active >= concurrency
            or used_cpu + limits.cpu_seconds * settings.verification_max_attempts > cpu
            or used_memory
            + limits.memory_bytes * limits.wall_seconds * settings.verification_max_attempts
            > memory
        ):
            raise QuotaExceeded("verification_budget_exhausted")

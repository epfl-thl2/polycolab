"""Bounded, tenant-interleaved claim discovery; not a capacity allocator.

The caller must still reauthorize and fence each candidate under the existing
lock order. Queue ranks are a snapshot, not a durable scheduling entitlement.
"""

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlVerificationJob
from polycolab.entities.enums import VerificationJobState


def candidate_page(session: Session, *, limit: int = 100) -> list[UUID]:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid verification candidate page limit")
    # Rank a user's jobs across all workspaces: creating more workspaces must
    # not give one sponsor multiple first-in-user positions.
    users = (
        select(
            SqlVerificationJob.id,
            SqlVerificationJob.ownership_scope_id,
            SqlVerificationJob.queued_at,
            func.row_number()
            .over(
                partition_by=SqlVerificationJob.sponsor_user_id,
                order_by=(SqlVerificationJob.queued_at, SqlVerificationJob.id),
            )
            .label("user_rank"),
        )
        .where(SqlVerificationJob.state == VerificationJobState.QUEUED)
        .subquery()
    )
    # Within each workspace, interleave users before assigning workspace ranks.
    # Ranking by FIFO alone here would hide a new user's job behind a busy
    # neighbor in the very same workspace.
    scopes = select(
        users.c.id,
        users.c.queued_at,
        users.c.user_rank,
        func.row_number()
        .over(
            partition_by=users.c.ownership_scope_id,
            order_by=(users.c.user_rank, users.c.queued_at, users.c.id),
        )
        .label("scope_rank"),
    ).subquery()
    rank = case(
        (scopes.c.user_rank > scopes.c.scope_rank, scopes.c.user_rank),
        else_=scopes.c.scope_rank,
    )
    return list(
        session.scalars(
            select(scopes.c.id).order_by(rank, scopes.c.queued_at, scopes.c.id).limit(limit)
        )
    )

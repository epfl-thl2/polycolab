"""Private executor identity and slot ownership, serialized with allocation."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlHostedExecutor, SqlHostedSlot
from polycolab.entities.time import utc_now
from polycolab.execution.allocator import _serialize, utc


class HostConflict(Exception):
    pass


def advertise(
    session: Session,
    *,
    worker_id: str,
    incarnation: str,
    image: str,
    states: dict[int, str],
    protocol: int,
) -> None:
    if protocol != 3 or not states or set(states) != set(range(len(states))):
        raise HostConflict("executor_protocol_mismatch")
    _serialize(session)
    row = session.get(SqlHostedExecutor, worker_id)
    if row is not None and row.incarnation != incarnation and utc(row.expires_at) > utc_now():
        raise HostConflict("executor_incarnation_conflict")
    if row is None:
        row = SqlHostedExecutor(worker_id=worker_id)
        session.add(row)
    row.incarnation, row.protocol_version, row.image_digest = incarnation, protocol, image
    row.capacity = sum(state != "QUARANTINED" for state in states.values())
    row.expires_at = utc_now() + timedelta(seconds=45)
    session.flush()
    for ordinal, state in states.items():
        slot = session.get(SqlHostedSlot, (worker_id, ordinal))
        if slot is None:
            slot = SqlHostedSlot(worker_id=worker_id, ordinal=ordinal)
            session.add(slot)
        if state == "QUARANTINED":
            slot.quarantined = True
        elif slot.run_id is None:
            slot.quarantined = False
    for slot in session.scalars(select(SqlHostedSlot).where(SqlHostedSlot.worker_id == worker_id)):
        if slot.ordinal not in states:
            slot.quarantined = True
    session.flush()
    row.capacity = (
        session.scalar(
            select(func.count())
            .select_from(SqlHostedSlot)
            .where(
                SqlHostedSlot.worker_id == worker_id,
                SqlHostedSlot.ordinal < len(states),
                SqlHostedSlot.quarantined.is_(False),
            )
        )
        or 0
    )
    session.commit()


def release_elapsed(session: Session) -> int:
    from polycolab.db.models import SqlExecutionSlotLease

    _serialize(session)
    count = 0
    for slot in session.scalars(
        select(SqlHostedSlot)
        .where(
            SqlHostedSlot.quarantined.is_(False),
            SqlHostedSlot.run_id.is_not(None),
        )
        .limit(100)
        .with_for_update()
    ):
        lease = session.scalar(
            select(SqlExecutionSlotLease)
            .where(
                SqlExecutionSlotLease.owner_id == slot.worker_id,
                SqlExecutionSlotLease.agent_run_id == slot.run_id,
                SqlExecutionSlotLease.generation == slot.generation,
            )
            .with_for_update()
        )
        if lease is not None and utc(lease.safe_release_at) <= utc_now():
            if lease.released_at is None:
                lease.released_at = utc_now()
            slot.run_id = slot.generation = None
            count += 1
    session.commit()
    return count

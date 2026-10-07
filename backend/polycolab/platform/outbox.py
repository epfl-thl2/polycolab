"""Transactional outbox primitives for bounded, idempotent consumers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlOutboxConsumerReceipt, SqlOutboxEvent
from polycolab.entities.enums import OutboxEventStatus
from polycolab.entities.time import utc_now


class OutboxInvalid(Exception):
    pass


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def append_event(
    session: Session,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict[str, object],
    ownership_scope_id: UUID | None = None,
) -> SqlOutboxEvent:
    if not 1 <= len(event_type) <= 100 or not 1 <= len(aggregate_type) <= 64:
        raise OutboxInvalid
    event = SqlOutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        ownership_scope_id=ownership_scope_id,
        payload=payload,
        payload_digest=canonical_digest(payload),
    )
    session.add(event)
    session.flush()
    return event


def claim_events(
    session: Session,
    *,
    consumer_name: str,
    limit: int = 100,
    now: datetime | None = None,
    lease_seconds: int = 60,
    max_attempts: int = 5,
) -> list[SqlOutboxEvent]:
    if (
        not 1 <= len(consumer_name) <= 100
        or not 1 <= limit <= 100
        or not 1 <= lease_seconds <= 300
        or not 1 <= max_attempts <= 100
    ):
        raise OutboxInvalid
    now = now or utc_now()
    delivered_for_consumer = exists(
        select(SqlOutboxConsumerReceipt.id).where(
            SqlOutboxConsumerReceipt.event_id == SqlOutboxEvent.id,
            SqlOutboxConsumerReceipt.consumer_name == consumer_name,
            or_(
                SqlOutboxConsumerReceipt.outcome == "DELIVERED",
                SqlOutboxConsumerReceipt.attempts >= max_attempts,
            ),
        )
    )
    events = list(
        session.scalars(
            select(SqlOutboxEvent)
            .where(
                SqlOutboxEvent.available_at <= now,
                ~delivered_for_consumer,
            )
            .order_by(SqlOutboxEvent.created_at, SqlOutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    for event in events:
        receipt = session.scalar(
            select(SqlOutboxConsumerReceipt).where(
                SqlOutboxConsumerReceipt.event_id == event.id,
                SqlOutboxConsumerReceipt.consumer_name == consumer_name,
            )
        )
        if receipt is None:
            receipt = SqlOutboxConsumerReceipt(
                event_id=event.id, consumer_name=consumer_name, outcome="CLAIMED", attempts=0
            )
            session.add(receipt)
        receipt.attempts += 1
        receipt.outcome = "CLAIMED"
        event.status = OutboxEventStatus.CLAIMED
        event.attempts += 1
        event.claimed_by = consumer_name
        event.claimed_at = now
        event.available_at = now + timedelta(seconds=lease_seconds)
    session.commit()
    return events


def record_consumer_receipt(
    session: Session,
    *,
    event_id: UUID,
    consumer_name: str,
    success: bool,
    claim_generation: int,
    error: str | None = None,
    retry_after: timedelta = timedelta(seconds=30),
    now: datetime | None = None,
) -> SqlOutboxConsumerReceipt:
    if not 1 <= len(consumer_name) <= 100 or not timedelta(0) <= retry_after <= timedelta(days=1):
        raise OutboxInvalid
    event = session.scalar(
        select(SqlOutboxEvent)
        .where(SqlOutboxEvent.id == event_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if event is None:
        raise OutboxInvalid
    # Lock acquisition may outlast the lease; evaluate expiry after acquiring it.
    now = now or utc_now()
    receipt = session.scalar(
        select(SqlOutboxConsumerReceipt)
        .where(
            SqlOutboxConsumerReceipt.event_id == event_id,
            SqlOutboxConsumerReceipt.consumer_name == consumer_name,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if receipt is not None:
        if receipt.outcome == "DELIVERED":
            return receipt
    if (
        event.status is not OutboxEventStatus.CLAIMED
        or event.claimed_by != consumer_name
        or event.attempts != claim_generation
        or event.available_at.replace(tzinfo=UTC) <= now
    ):
        raise OutboxInvalid
    if receipt is not None:
        receipt.outcome = "DELIVERED" if success else "FAILED"
        receipt.last_error = None if success else (error or "consumer failed")[:500]
    else:
        receipt = SqlOutboxConsumerReceipt(
            event_id=event_id,
            consumer_name=consumer_name,
            outcome="DELIVERED" if success else "FAILED",
            attempts=event.attempts,
            last_error=None if success else (error or "consumer failed")[:500],
        )
        session.add(receipt)
    event.status = OutboxEventStatus.DELIVERED if success else OutboxEventStatus.FAILED
    event.claimed_by = None
    event.claimed_at = None
    event.available_at = now if success else now + retry_after
    session.flush()
    return receipt

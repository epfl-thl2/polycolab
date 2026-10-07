from __future__ import annotations

from datetime import timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event as sqlalchemy_event

import polycolab.platform.outbox as outbox_domain
from polycolab.db.models import SqlOutboxEvent
from polycolab.entities.enums import OutboxEventStatus
from polycolab.entities.time import utc_now
from polycolab.platform.outbox import (
    OutboxInvalid,
    append_event,
    claim_events,
    record_consumer_receipt,
)


def test_outbox_claim_retry_and_consumer_receipt_are_bounded_and_idempotent(
    client: TestClient,
) -> None:
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        event = append_event(
            session,
            event_type="research.changed",
            aggregate_type="research_object",
            aggregate_id=uuid4(),
            payload={"revision": "r1"},
        )
        session.commit()

        claimed = claim_events(session, consumer_name="search", limit=1)
        assert [item.id for item in claimed] == [event.id]
        assert claimed[0].status is OutboxEventStatus.CLAIMED
        failed = record_consumer_receipt(
            session,
            event_id=event.id,
            consumer_name="search",
            success=False,
            claim_generation=1,
            error="temporary",
        )
        session.commit()
        assert failed.outcome == "FAILED"

        retry_now = utc_now() + timedelta(seconds=31)
        retry = claim_events(session, consumer_name="search", now=retry_now)
        assert [item.id for item in retry] == [event.id]
        delivered = record_consumer_receipt(
            session,
            event_id=event.id,
            consumer_name="search",
            success=True,
            claim_generation=2,
            now=retry_now,
        )
        session.commit()
        assert delivered is failed
        assert delivered.outcome == "DELIVERED"

        duplicate = record_consumer_receipt(
            session,
            event_id=event.id,
            consumer_name="search",
            success=True,
            claim_generation=2,
        )
        assert duplicate.id == delivered.id
        stored = session.get(SqlOutboxEvent, event.id)
        assert stored is not None
        assert stored.status is OutboxEventStatus.DELIVERED
        assert stored.attempts == 2
    finally:
        session.close()


def test_lost_claim_is_fenced_and_retry_exhaustion_is_per_consumer(client: TestClient) -> None:
    with cast(Any, client.app).state.session_factory() as db:
        event = append_event(
            db, event_type="test", aggregate_type="test", aggregate_id=uuid4(), payload={}
        )
        db.commit()
        start = utc_now()
        assert len(claim_events(db, consumer_name="search", now=start, max_attempts=2)) == 1
        assert claim_events(db, consumer_name="search", now=start + timedelta(seconds=1)) == []
        assert (
            len(
                claim_events(
                    db, consumer_name="search", now=start + timedelta(seconds=61), max_attempts=2
                )
            )
            == 1
        )
        with pytest.raises(OutboxInvalid):
            record_consumer_receipt(
                db,
                event_id=event.id,
                consumer_name="search",
                success=True,
                claim_generation=1,
                now=start + timedelta(seconds=62),
            )
        assert (
            claim_events(
                db, consumer_name="search", now=start + timedelta(seconds=122), max_attempts=2
            )
            == []
        )
        assert (
            len(
                claim_events(
                    db,
                    consumer_name="notifications",
                    now=start + timedelta(seconds=122),
                    max_attempts=2,
                )
            )
            == 1
        )
        with pytest.raises(OutboxInvalid):
            record_consumer_receipt(
                db,
                event_id=event.id,
                consumer_name="search",
                success=True,
                claim_generation=2,
                now=start + timedelta(seconds=123),
            )


def test_completion_rechecks_time_after_waiting_for_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        value = append_event(
            db, event_type="test", aggregate_type="test", aggregate_id=uuid4(), payload={}
        )
        db.commit()
        start = utc_now()
        claim_events(db, consumer_name="search", now=start, lease_seconds=60)
        clock = [start]
        monkeypatch.setattr(outbox_domain, "utc_now", lambda: clock[0])

        def lock_delay(*_: object) -> None:
            # Simulate time spent waiting in the database, without a wall-clock sleep.
            clock[0] = start + timedelta(seconds=61)

        sqlalchemy_event.listen(app.state.engine, "after_cursor_execute", lock_delay)
        try:
            with pytest.raises(OutboxInvalid):
                record_consumer_receipt(
                    db, event_id=value.id, consumer_name="search", success=True, claim_generation=1
                )
        finally:
            sqlalchemy_event.remove(app.state.engine, "after_cursor_execute", lock_delay)

"""Candidate-query checks, not PostgreSQL contention or throughput evidence."""

from collections.abc import Iterator
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, create_engine
from sqlalchemy.orm import Session
from test_research_domain import add_member, current_user_id
from test_verification import admit, claim, setup_job

from polycolab.entities.time import utc_now
from polycolab.verification import service as verification
from polycolab.verification.queue import candidate_page


@pytest.fixture
def queue() -> Iterator[tuple[Session, Table]]:
    # Test precisely the read projection; lifecycle/FK authorization continues to
    # be covered through the full models in test_verification.py.
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    table = Table(
        "verification_jobs",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("ownership_scope_id", Uuid, nullable=False),
        Column("sponsor_user_id", Uuid, nullable=False),
        Column("queued_at", DateTime(timezone=True), nullable=False),
        Column("state", String, nullable=False),
    )
    metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session, table
    finally:
        engine.dispose()


def insert(queue: tuple[Session, Table], user: UUID, scope: UUID, count: int) -> list[UUID]:
    session, table = queue
    ids = [uuid4() for _ in range(count)]
    now = utc_now()
    session.execute(
        table.insert(),
        [
            {
                "id": identity,
                "ownership_scope_id": scope,
                "sponsor_user_id": user,
                "queued_at": now + timedelta(microseconds=index),
                "state": "QUEUED",
            }
            for index, identity in enumerate(ids)
        ],
    )
    session.commit()
    return ids


@pytest.mark.parametrize("shared_scope", [False, True])
def test_busy_sponsor_cannot_fill_discovery_page(
    queue: tuple[Session, Table], shared_scope: bool
) -> None:
    scope = uuid4()
    busy = insert(queue, uuid4(), scope, 100)
    quiet = insert(queue, uuid4(), scope if shared_scope else uuid4(), 1)[0]
    page = candidate_page(queue[0])
    assert len(page) == 100
    assert page[:2] == [busy[0], quiet]
    assert page.index(quiet) < page.index(busy[1])


def test_many_projects_do_not_multiply_sponsor_first_positions(
    queue: tuple[Session, Table],
) -> None:
    user = uuid4()
    busy = [insert(queue, user, uuid4(), 1)[0] for _ in range(100)]
    quiet = insert(queue, uuid4(), uuid4(), 1)[0]
    assert candidate_page(queue[0], limit=2) == [busy[0], quiet]


def test_one_project_with_many_users_does_not_hide_another(
    queue: tuple[Session, Table],
) -> None:
    scope = uuid4()
    busy = [insert(queue, uuid4(), scope, 1)[0] for _ in range(100)]
    quiet = insert(queue, uuid4(), uuid4(), 1)[0]
    assert candidate_page(queue[0], limit=2) == [busy[0], quiet]


def test_fifo_terminal_exclusion_and_repeatability(queue: tuple[Session, Table]) -> None:
    session, table = queue
    ids = insert(queue, uuid4(), uuid4(), 5)
    session.execute(table.update().where(table.c.id == ids[0]).values(state="RUNNING"))
    session.commit()
    assert candidate_page(session) == ids[1:]
    assert candidate_page(session) == ids[1:]


@pytest.mark.parametrize("limit", [0, -1, 101, True])
def test_page_limits_are_explicit(queue: tuple[Session, Table], limit: int) -> None:
    with pytest.raises(ValueError, match="candidate page limit"):
        candidate_page(queue[0], limit=limit)


def test_claim_reaches_quiet_user_behind_full_page_of_cooling_retries(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, user, submission = setup_job(client)
    settings = app.state.settings
    settings.verification_user_concurrent_jobs = 100
    settings.verification_project_concurrent_jobs = 200
    settings.verification_user_daily_cpu_seconds = 100_000
    settings.verification_project_daily_cpu_seconds = 100_000
    settings.verification_user_daily_memory_byte_seconds = 10**18
    settings.verification_project_daily_memory_byte_seconds = 10**18
    add_member(client, str(submission.project_id), "contributor", "CONTRIBUTOR")
    quiet_user = UUID(current_user_id(client, "contributor"))
    for index in range(100):
        admit(app, user, submission, f"busy-{index}")
        claim(app)
    now = utc_now() + timedelta(seconds=31)
    monkeypatch.setattr(verification, "utc_now", lambda: now)
    with app.state.session_factory() as session:
        assert verification.recover(session) == 100
    quiet = admit(app, quiet_user, submission, "quiet")
    # All 100 older attempts still have possible processes within their 60s
    # wall bound. Discovery must reach the new user without reclaiming them.
    assert claim(app).job_id == quiet.id

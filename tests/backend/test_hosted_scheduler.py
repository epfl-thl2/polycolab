"""Hosted scheduling on SQLite and disposable PostgreSQL schemas."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_codex_runtime import spec
from test_runtime_api import _queue_run
from test_scheduling_foundation import scheduler_pg_schema as scheduler_pg_schema

from polycolab.agents.sessions import append_user_message_and_queue_run, create_agent_session
from polycolab.app.application import create_app
from polycolab.db.models import SqlAgentRun, SqlExecutionSlotLease, SqlUser
from polycolab.entities.enums import AgentRunStatus, PlatformAgentKind
from polycolab.entities.time import utc_now
from polycolab.execution import allocator
from polycolab.platform.config import Settings


@pytest.fixture(params=["sqlite", "postgres"])
def hosted_client(request: pytest.FixtureRequest, client: TestClient) -> Iterator[TestClient]:
    if request.param == "sqlite":
        yield client
        return
    _, config, url = request.getfixturevalue("scheduler_pg_schema")
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-hosted-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    with TestClient(app) as pg:
        yield pg
    app.state.engine.dispose()


def new_hosted(client: TestClient, ancestor: UUID | None = None) -> UUID:
    app = cast(Any, client.app)
    if ancestor is None:
        _, ancestor = _queue_run(client)
        with app.state.session_factory() as db:
            old = db.get(SqlAgentRun, ancestor)
            old.status, old.finished_at = AgentRunStatus.FAILED, utc_now()
            user = db.get(SqlUser, old.requested_by_user_id)
            user.subject = "hosted-" + uuid4().hex
            db.commit()
    with app.state.session_factory() as db:
        previous = db.get(SqlAgentRun, ancestor)
        parent = create_agent_session(
            db,
            project_id=previous.project_id,
            created_by_user_id=previous.requested_by_user_id,
            agent_kind=PlatformAgentKind.RESEARCHER,
        )
        _, run = append_user_message_and_queue_run(
            db,
            session_id=parent.id,
            requested_by_user_id=previous.requested_by_user_id,
            gateway_profile_id=previous.gateway_profile_id,
            content_md="Hosted execution",
            deadline_at=utc_now() + timedelta(minutes=5),
            runtime_spec=spec().model_dump(mode="json"),
        )
        return run.id


def claim(client: TestClient, worker: str, capacity: int = 4, tenant: int = 2) -> UUID | None:
    app = cast(Any, client.app)
    with app.state.session_factory() as db:
        result = allocator.claim(
            db,
            worker_id=worker,
            lease_seconds=30,
            capacity=capacity,
            user_capacity=tenant,
            project_capacity=tenant,
        )
        return result.id if result else None


def test_hosted_capacity_tenant_limits_and_positive_termination(hosted_client: TestClient) -> None:
    first = new_hosted(hosted_client)
    new_hosted(hosted_client, first)
    new_hosted(hosted_client, first)
    second = new_hosted(hosted_client)
    new_hosted(hosted_client, second)
    new_hosted(hosted_client, second)
    claimed = [claim(hosted_client, f"worker-{index}") for index in range(4)]
    assert all(claimed) and len(set(claimed)) == 4
    assert claim(hosted_client, "full") is None
    app = cast(Any, hosted_client.app)
    with app.state.session_factory() as db:
        slots = list(db.scalars(select(SqlExecutionSlotLease)))
        assert len(slots) == 4
        slot = slots[0]
        # Logical expiry cannot release physical occupancy.
        run = db.get(SqlAgentRun, slot.agent_run_id)
        run.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
        assert claim(hosted_client, "expired") is None
        allocator.confirm_termination(
            db, run_id=slot.agent_run_id, generation=slot.generation, owner=slot.owner_id
        )
    assert claim(hosted_client, "replacement") is not None


def test_hosted_concurrent_claims_never_exceed_global_capacity(hosted_client: TestClient) -> None:
    app = cast(Any, hosted_client.app)
    if app.state.engine.dialect.name != "postgresql":
        pytest.skip("real PostgreSQL contention evidence only")
    for _ in range(6):
        new_hosted(hosted_client)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: claim(hosted_client, f"concurrent-{i}"), range(8)))
    claimed = [value for value in results if value]
    assert len(claimed) == len(set(claimed)) == 4


def test_executor_identity_and_quarantine_fence(hosted_client: TestClient) -> None:
    from polycolab.agents.runtime.errors import RuntimeApiConflict
    from polycolab.execution.hosts import advertise

    run_id = new_hosted(hosted_client)
    app = cast(Any, hosted_client.app)
    with app.state.session_factory() as db:
        advertise(
            db,
            worker_id="host",
            incarnation="current",
            image="0" * 64,
            states={0: "AVAILABLE", 1: "QUARANTINED"},
            protocol=4,
        )

        def attempt(incarnation: str, slot_id: int) -> SqlAgentRun | None:
            return allocator.claim(
                db,
                incarnation=incarnation,
                slot_id=slot_id,
                worker_id="host",
                lease_seconds=30,
                capacity=4,
                user_capacity=2,
                project_capacity=2,
                image_digest="0" * 64,
            )

        with pytest.raises(RuntimeApiConflict, match="executor_not_ready"):
            attempt("stale", 0)
        assert attempt("current", 1) is None
        run = attempt("current", 0)
        assert run is not None and run.id == run_id
        assert attempt("current", 0) is None
        advertise(
            db,
            worker_id="host",
            incarnation="current",
            image="0" * 64,
            states={0: "QUARANTINED", 1: "QUARANTINED"},
            protocol=4,
        )
        from polycolab.execution.hosts import release_elapsed

        assert release_elapsed(db) == 0
        allocator.confirm_termination(
            db, run_id=run.id, generation=run.lease_generation, owner="host"
        )
        from polycolab.db.models import SqlHostedSlot

        slot = db.get(SqlHostedSlot, ("host", 0))
        assert slot.run_id is None and not slot.quarantined


def test_timeout_receipt_survives_retry_on_real_schema(
    hosted_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from polycolab.agents import recovery
    from polycolab.db.models import SqlHostedCompletion

    run_id = new_hosted(hosted_client)
    assert claim(hosted_client, "timed-worker") == run_id
    app = cast(Any, hosted_client.app)
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        generation = run.lease_generation
        future = utc_now() + timedelta(minutes=10)
        monkeypatch.setattr(recovery, "utc_now", lambda: future)
        for _ in range(2):
            recovery.complete(
                db,
                run_id=run_id,
                worker_id="timed-worker",
                generation=generation,
                status=AgentRunStatus.TIMED_OUT,
                failure_code="deadline_exceeded",
                final_message_md=None,
            )
        assert db.get(SqlAgentRun, run_id).status == AgentRunStatus.TIMED_OUT
        assert db.get(SqlHostedCompletion, (run_id, generation)) is not None


@pytest.mark.parametrize(
    "previous_head", ["20260915_submission_numbers", "20260915_hosted_recovery"]
)
def test_merge_upgrade_preserves_existing_branch_data(
    scheduler_pg_schema: tuple[Any, Any, str], previous_head: str
) -> None:
    from sqlalchemy.orm import Session

    engine, config, _ = scheduler_pg_schema
    command.upgrade(config, previous_head)
    user_id = uuid4()
    with Session(engine) as db:
        db.add(SqlUser(id=user_id, issuer="merge-test", subject="retained-account"))
        db.commit()
    command.upgrade(config, "head")
    with Session(engine) as db:
        retained = db.get(SqlUser, user_id)
        assert retained is not None and retained.subject == "retained-account"
    from alembic.script import ScriptDirectory

    assert ScriptDirectory.from_config(config).get_heads() == ["20261012_projects"]

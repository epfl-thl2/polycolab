"""Shared scheduler persistence checks; no allocator or capacity evidence."""

import os
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from test_research_domain import create_object, create_workspace
from test_sessions_store import _new_run
from test_verification_foundation_postgresql import _job

from polycolab.agents.sessions import claim_next_run_in_transaction
from polycolab.app.application import create_app
from polycolab.db.models import (
    SqlAgentRun,
    SqlExecutionClassState,
    SqlExecutionFairnessState,
    SqlExecutionSlotLease,
    SqlExecutionWorkItem,
    SqlObjectRevision,
    SqlResearchScope,
    SqlVerificationAttempt,
    SqlVerificationEnvironment,
)
from polycolab.entities.enums import (
    ExecutionTenantKind,
    ExecutionWorkloadClass,
    VerificationLanguage,
)
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings, get_settings


def test_agent_work_item_and_slot_keep_physical_release_separate(
    client: TestClient,
) -> None:
    session, user, _, run_id = _new_run(client)
    try:
        run = session.get(SqlAgentRun, run_id)
        assert run is not None
        run.deadline_at = utc_now() + timedelta(minutes=5)
        session.commit()
        item = SqlExecutionWorkItem(
            agent_run_id=run.id,
            sponsor_user_id=user.id,
            project_id=run.project_id,
            workload_class=ExecutionWorkloadClass.AGENT,
            policy_version=1,
            reserved_cost=3,
            agent_model_tokens=100,
            agent_provider_cost_microusd=200,
            wall_seconds=300,
            queued_at=run.created_at,
        )
        session.add(item)
        session.add(
            SqlExecutionClassState(
                workload_class=ExecutionWorkloadClass.AGENT,
                active_policy_version=1,
            )
        )
        session.flush()
        session.add_all(
            [
                SqlExecutionFairnessState(
                    workload_class=ExecutionWorkloadClass.AGENT,
                    tenant_kind=ExecutionTenantKind.USER,
                    tenant_id=user.id,
                    policy_version=1,
                    virtual_runtime=0,
                ),
                SqlExecutionFairnessState(
                    workload_class=ExecutionWorkloadClass.AGENT,
                    tenant_kind=ExecutionTenantKind.WORKSPACE,
                    tenant_id=run.project_id,
                    policy_version=1,
                    virtual_runtime=0,
                ),
            ]
        )
        session.commit()

        claimed = claim_next_run_in_transaction(
            session, worker_id="scheduler", lease_for=timedelta(seconds=30)
        )
        assert claimed is not None and claimed.lease_expires_at is not None
        assert claimed.lease_acquired_at is not None
        assert claimed.deadline_at is not None
        slot = SqlExecutionSlotLease(
            work_item_id=item.id,
            workload_class=ExecutionWorkloadClass.AGENT,
            agent_run_id=claimed.id,
            generation=claimed.lease_generation,
            owner_id="scheduler",
            acquired_at=claimed.lease_acquired_at,
            lease_expires_at=claimed.lease_expires_at,
            safe_release_at=claimed.deadline_at,
        )
        session.add(slot)
        session.commit()

        slot.released_at = utc_now()
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        slot = session.get(SqlExecutionSlotLease, slot.id)
        assert slot is not None
        stopped = utc_now()
        slot.termination_confirmed_at = stopped
        slot.released_at = stopped - timedelta(microseconds=1)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        slot = session.get(SqlExecutionSlotLease, slot.id)
        assert slot is not None
        slot.termination_confirmed_at = stopped
        slot.released_at = stopped
        session.commit()

        impossible = SqlExecutionSlotLease(
            work_item_id=item.id,
            workload_class=ExecutionWorkloadClass.AGENT,
            agent_run_id=claimed.id,
            generation=claimed.lease_generation + 1,
            owner_id="scheduler",
            acquired_at=stopped,
            lease_expires_at=stopped - timedelta(seconds=1),
            safe_release_at=claimed.deadline_at,
        )
        session.add(impossible)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_work_item_resource_shape_fails_closed(client: TestClient) -> None:
    app = cast(Any, client.app)
    with app.state.session_factory() as session:
        invalid = SqlExecutionWorkItem(
            agent_run_id=None,
            verification_job_id=None,
            sponsor_user_id=UUID("00000000-0000-0000-0000-000000000001"),
            project_id=UUID("00000000-0000-0000-0000-000000000002"),
            workload_class=ExecutionWorkloadClass.AGENT,
            policy_version=1,
            reserved_cost=1,
            agent_model_tokens=1,
            agent_provider_cost_microusd=1,
            wall_seconds=1,
            queued_at=utc_now(),
        )
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.commit()


@pytest.fixture
def scheduler_pg_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Engine, Config, str]]:
    url = os.environ.get("M0_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("M0_POSTGRES_TEST_URL is required for scheduler trigger evidence")
    admin = create_engine(url)
    schema = "scheduler_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped = scoped_url.render_as_string(hide_password=False)
    engine = create_engine(scoped_url)
    monkeypatch.setenv("DATABASE_URL", scoped)
    get_settings.cache_clear()
    backend = Path(__file__).resolve().parents[2] / "backend"
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option(
        "script_location", str(backend / "polycolab" / "db" / "migrations" / "postgresql")
    )
    try:
        yield engine, config, scoped
    finally:
        engine.dispose()
        get_settings.cache_clear()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def _expect_pg_rejection(db: Session, slot: SqlExecutionSlotLease) -> None:
    with pytest.raises(DBAPIError), db.begin_nested():
        db.add(slot)
        db.flush()


def test_postgresql_slot_triggers_bind_class_owner_timestamps_and_attempt(
    scheduler_pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    engine, config, url = scheduler_pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-scheduler-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            session, user, _, run_id = _new_run(pg_client)
            try:
                claimed_at = utc_now()
                run = session.get(SqlAgentRun, run_id)
                assert run is not None
                run.deadline_at = claimed_at + timedelta(minutes=5)
                session.commit()
                item = SqlExecutionWorkItem(
                    agent_run_id=run.id,
                    sponsor_user_id=user.id,
                    project_id=run.project_id,
                    workload_class=ExecutionWorkloadClass.AGENT,
                    policy_version=1,
                    reserved_cost=1,
                    agent_model_tokens=10,
                    agent_provider_cost_microusd=10,
                    wall_seconds=300,
                    queued_at=run.created_at,
                )
                session.add(item)
                session.commit()
                claimed = claim_next_run_in_transaction(
                    session,
                    worker_id="scheduler",
                    lease_for=timedelta(seconds=30),
                    now=claimed_at,
                )
                assert claimed is not None
                session.commit()
                assert claimed.lease_acquired_at is not None
                assert claimed.lease_expires_at is not None
                assert claimed.deadline_at is not None

                common = {
                    "work_item_id": item.id,
                    "agent_run_id": claimed.id,
                    "generation": claimed.lease_generation,
                    "acquired_at": claimed.lease_acquired_at,
                    "lease_expires_at": claimed.lease_expires_at,
                    "safe_release_at": claimed.deadline_at,
                }
                _expect_pg_rejection(
                    session,
                    SqlExecutionSlotLease(
                        **common,
                        workload_class=ExecutionWorkloadClass.PYTHON,
                        owner_id="scheduler",
                    ),
                )
                _expect_pg_rejection(
                    session,
                    SqlExecutionSlotLease(
                        **common,
                        workload_class=ExecutionWorkloadClass.AGENT,
                        owner_id="other-worker",
                    ),
                )
                invalid_times = common | {
                    "acquired_at": claimed.lease_expires_at + timedelta(seconds=1)
                }
                _expect_pg_rejection(
                    session,
                    SqlExecutionSlotLease(
                        **invalid_times,
                        workload_class=ExecutionWorkloadClass.AGENT,
                        owner_id="scheduler",
                    ),
                )
                slot = SqlExecutionSlotLease(
                    **common,
                    workload_class=ExecutionWorkloadClass.AGENT,
                    owner_id="scheduler",
                )
                session.add(slot)
                session.commit()
                slot.termination_confirmed_at = utc_now() + timedelta(seconds=2)
                slot.released_at = utc_now()
                with pytest.raises(DBAPIError):
                    session.commit()
                session.rollback()
            finally:
                session.close()

            project_id = create_workspace(pg_client)
            record = create_object(pg_client, project_id, kind="COMPUTATION")
        with app.state.session_factory() as db:
            revision = db.get(SqlObjectRevision, UUID(record["current_object_version_id"]))
            assert revision is not None
            scope = db.scalar(
                select(SqlResearchScope).where(SqlResearchScope.id == revision.ownership_scope_id)
            )
            assert scope is not None and scope.project_id is not None
            environment = SqlVerificationEnvironment(
                language=VerificationLanguage.PYTHON,
                image_digest="1" * 64,
                toolchain_version="CPython 3.13.7",
                dependency_lock_digest="2" * 64,
                build_digest="3" * 64,
                platform_identity="linux-amd64-sbx",
                max_cpu_count=2,
                max_cpu_seconds=600,
                max_wall_seconds=300,
                max_memory_bytes=1024 * 1024 * 1024,
                max_process_count=32,
                max_disk_bytes=1024 * 1024 * 1024,
                max_output_bytes=1024 * 1024,
                max_log_bytes=65_536,
                max_output_files=16,
            )
            db.add(environment)
            db.flush()
            first = _job(revision, environment)
            second = _job(revision, environment)
            db.add_all((first, second))
            db.flush()
            items = []
            for job in (first, second):
                item = SqlExecutionWorkItem(
                    verification_job_id=job.id,
                    sponsor_user_id=job.sponsor_user_id,
                    project_id=scope.project_id,
                    workload_class=ExecutionWorkloadClass.PYTHON,
                    policy_version=1,
                    reserved_cost=1,
                    verification_cpu_seconds=job.cpu_seconds,
                    verification_memory_byte_seconds=job.memory_bytes * job.wall_seconds,
                    wall_seconds=job.wall_seconds,
                    queued_at=job.queued_at,
                )
                db.add(item)
                items.append(item)
            db.flush()
            started = utc_now()
            attempts = [
                SqlVerificationAttempt(
                    job_id=job.id,
                    generation=1,
                    controller_id="controller",
                    lease_expires_at=started + timedelta(seconds=30),
                    started_at=started,
                )
                for job in (first, second)
            ]
            db.add_all(attempts)
            db.commit()
            safe_release = min(first.deadline_at, started + timedelta(seconds=first.wall_seconds))
            _expect_pg_rejection(
                db,
                SqlExecutionSlotLease(
                    work_item_id=items[0].id,
                    workload_class=ExecutionWorkloadClass.PYTHON,
                    verification_attempt_id=attempts[0].id,
                    generation=1,
                    owner_id="other-controller",
                    acquired_at=started,
                    lease_expires_at=attempts[0].lease_expires_at,
                    safe_release_at=safe_release,
                ),
            )
            _expect_pg_rejection(
                db,
                SqlExecutionSlotLease(
                    work_item_id=items[0].id,
                    workload_class=ExecutionWorkloadClass.PYTHON,
                    verification_attempt_id=attempts[1].id,
                    generation=1,
                    owner_id="controller",
                    acquired_at=started,
                    lease_expires_at=attempts[1].lease_expires_at,
                    safe_release_at=safe_release,
                ),
            )
    finally:
        app.state.engine.dispose()

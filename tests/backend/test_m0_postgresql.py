"""Real PostgreSQL baseline, integrity, and concurrency acceptance.

M0_POSTGRES_TEST_URL must identify a disposable database. Each test creates and
drops only its own random schema.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from polycolab.access.actors import human_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import (
    SqlCommunityDeliveryCursor,
    SqlContributionEnvelope,
    SqlMembership,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlOutboxEvent,
    SqlProject,
    SqlResearchActivityEvent,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    ResearchObjectKind,
    ResearchScopeKind,
    WorkspaceRole,
    WorkspaceVisibility,
)
from polycolab.entities.time import utc_now
from polycolab.operations.telemetry import community_outbox_snapshot
from polycolab.platform.config import Settings, get_settings
from polycolab.platform.outbox import canonical_digest, claim_events, record_consumer_receipt
from polycolab.research.contributions import ContributionOutput, record_contribution
from polycolab.research.objects import StaleRevision, create_object, create_revision
from polycolab.workspaces.service import create_workspace


def test_postgresql_proposal_batch_retains_agent_provenance(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    from test_proposals_api import (
        test_selected_proposal_decisions_are_atomic_and_replay_as_one_batch,
    )

    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(
            database_url=url,
            web_dist_dir="/missing-m0-web-dist",
            feature_agent_execution_enabled=True,
        ),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            test_selected_proposal_decisions_are_atomic_and_replay_as_one_batch(pg_client)
    finally:
        app.state.engine.dispose()


def test_revocation_wins_against_waiting_workspace_writer(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    _, project_id, scope_id = seed(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = SqlUser(issuer="test", subject="contributor")
        db.add(user)
        db.flush()
        db.add(
            SqlMembership(project_id=project_id, user_id=user.id, role=WorkspaceRole.CONTRIBUTOR)
        )
        db.commit()
        user_id = user.id
    waiting = Event()

    def before_query(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
        if "FROM projects" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def write() -> None:
        with Session(engine) as db:
            user = db.get(SqlUser, user_id)
            assert user
            # Populate stale identity-map state before authorization waits.
            db.get(
                SqlMembership,
                db.scalar(select(SqlMembership.id).where(SqlMembership.user_id == user_id)),
            )
            event.listen(db.connection(), "before_cursor_execute", before_query)
            create_object(
                db,
                project_id=project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="must not commit",
                content_md="body",
                rationale=None,
            )

    with Session(engine) as revoker, ThreadPoolExecutor(1) as pool:
        revoker.scalar(select(SqlProject).where(SqlProject.id == project_id).with_for_update())
        membership = revoker.scalar(
            select(SqlMembership).where(SqlMembership.user_id == user_id).with_for_update()
        )
        assert membership
        membership.role = WorkspaceRole.READ_ONLY
        future = pool.submit(write)
        try:
            assert waiting.wait(timeout=10)
        finally:
            revoker.commit()
        with pytest.raises(AuthorizationDenied):
            future.result(timeout=10)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SqlResearchObject)) == 0


def test_postgresql_atomic_failure_rolls_back_all_mutation_rows(
    pg_schema: tuple[Engine, Config, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import polycolab.research.contributions as contributions

    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, scope_id = seed(engine)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr(contributions, "append_event", fail)
    with Session(engine) as db:
        user = db.get(SqlUser, user_id)
        assert user

        def output(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
            _, rev = create_object(
                db,
                project_id=project_id,
                author=user,
                kind=ResearchObjectKind.CLAIM,
                title="rollback",
                content_md="body",
                rationale=None,
                contribution=envelope,
                commit=False,
            )
            return [ContributionOutput("OBJECT_REVISION", rev.id, scope_id)]

        with pytest.raises(RuntimeError, match="injected failure"):
            record_contribution(
                db,
                actor=human_actor(user_id),
                operation="create",
                idempotency_key="failure",
                request_payload={},
                ownership_scope_id=scope_id,
                create_outputs=output,
            )
        for table in (
            SqlResearchObject,
            SqlObjectRevision,
            SqlContributionEnvelope,
            SqlMutationReceipt,
        ):
            assert db.scalar(select(func.count()).select_from(table)) == 0


@pytest.fixture
def pg_schema(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Engine, Config, str]]:
    url = os.environ.get("M0_POSTGRES_TEST_URL")
    if not url:
        pytest.skip("M0_POSTGRES_TEST_URL is required for real PostgreSQL evidence")
    admin = create_engine(url)
    schema = "m0_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped_url = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    scoped = scoped_url.render_as_string(hide_password=False)
    engine = create_engine(scoped_url)
    monkeypatch.setenv("DATABASE_URL", scoped)
    get_settings.cache_clear()
    backend = Path(__file__).resolve().parents[2] / "src/backend"
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
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def seed(engine: Engine) -> tuple[UUID, UUID, UUID]:
    with Session(engine, expire_on_commit=False) as db:
        user = SqlUser(issuer="test", subject="owner")
        db.add(user)
        db.commit()
        project = create_workspace(
            SqlAlchemyTransaction(db),
            creator=user,
            name="Private",
            description=None,
            visibility=WorkspaceVisibility.PRIVATE,
        )
        scope = db.scalar(select(SqlResearchScope).where(SqlResearchScope.project_id == project.id))
        assert scope is not None
        return user.id, project.id, scope.id


def test_fresh_baseline_matches_models_and_rejects_old_revision(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        assert differences == []
        assert (
            connection.scalar(
                text("SELECT count(*) FROM research_scopes WHERE scope_kind='COMMONS'")
            )
            == 1
        )
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='20260905_0014'"))
    with pytest.raises(Exception, match="Can't locate revision"):
        command.upgrade(config, "head")


def test_postgresql_community_snapshot_uses_concurrent_index_and_local_timeout(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    assert "ix_outbox_events_created_at" in {
        index["name"] for index in inspect(engine).get_indexes("outbox_events")
    }
    observed_at = utc_now()
    with Session(engine) as session:
        pending_payload = {"private": "never selected"}
        pending = SqlOutboxEvent(
            id=uuid4(),
            event_type="research.created",
            aggregate_type="OBJECT_REVISION",
            aggregate_id=uuid4(),
            payload=pending_payload,
            payload_digest=canonical_digest(pending_payload),
            created_at=observed_at - timedelta(seconds=7),
        )
        completed = SqlOutboxEvent(
            id=uuid4(),
            event_type="research.created",
            aggregate_type="OBJECT_REVISION",
            aggregate_id=uuid4(),
            payload={},
            payload_digest=canonical_digest({}),
            created_at=observed_at - timedelta(seconds=20),
        )
        session.add_all((pending, completed))
        session.flush()
        session.add(SqlCommunityDeliveryCursor(event_id=completed.id, done=True))
        session.commit()

        snapshot = community_outbox_snapshot(session, now=observed_at, statement_timeout_ms=250)
        assert snapshot.pending_events == 1
        assert snapshot.oldest_pending_age_seconds == 7
        assert session.scalar(text("SHOW statement_timeout")) == "250ms"


def test_workspace_and_commons_have_complete_immutable_revisions(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, _ = seed(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = db.get(SqlUser, user_id)
        commons = db.scalar(
            select(SqlResearchScope).where(SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS)
        )
        assert user and commons
        obj, revision = create_object(
            db,
            author=user,
            ownership_scope_id=commons.id,
            kind=ResearchObjectKind.CLAIM,
            title="Commons",
            content_md="body",
            rationale=None,
        )
        assert (
            db.scalar(
                select(SqlResearchScope.project_id).where(
                    SqlResearchScope.id == obj.ownership_scope_id
                )
            )
            is None
        )
        assert db.get(SqlStatementRevision, revision.id)
        private, private_revision = create_object(
            db,
            project_id=project_id,
            author=user,
            kind=ResearchObjectKind.CLAIM,
            title="Private",
            content_md="body",
            rationale=None,
        )
        _, newer = create_revision(
            db,
            project_id=project_id,
            object_id=private.id,
            base_revision_id=private_revision.id,
            author=user,
            title="Second",
            content_md="second",
            rationale=None,
        )
        assert newer.number == 2
        object_id, revision_id = obj.id, revision.id
    for sql, params in [
        ("UPDATE object_revisions SET content_md='tampered' WHERE id=:id", {"id": revision_id}),
        ("DELETE FROM statement_revisions WHERE revision_id=:id", {"id": revision_id}),
        ("UPDATE research_objects SET current_revision_id=NULL WHERE id=:id", {"id": object_id}),
        (
            "UPDATE research_objects SET ownership_scope_id=:scope WHERE id=:id",
            {"id": object_id, "scope": private.ownership_scope_id},
        ),
        (
            "UPDATE research_objects SET current_revision_id=:rev WHERE id=:id",
            {"id": object_id, "rev": newer.id},
        ),
    ]:
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text(sql), params)


def test_incomplete_metadata_and_late_attachments_are_rejected(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, _ = seed(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = db.get(SqlUser, user_id)
        assert user
        obj, rev = create_object(
            db,
            project_id=project_id,
            author=user,
            kind=ResearchObjectKind.CLAIM,
            title="statement",
            content_md="text",
            rationale=None,
        )
        proof, proof_rev = create_object(
            db,
            project_id=project_id,
            author=user,
            kind=ResearchObjectKind.NOTE,
            title="record",
            content_md="text",
            rationale=None,
        )
        with pytest.raises(DBAPIError):
            db.execute(
                text("INSERT INTO record_statement_links VALUES (:record,:statement)"),
                {"record": proof_rev.id, "statement": rev.id},
            )
            db.commit()
        db.rollback()
        bad = SqlObjectRevision(
            object_id=obj.id,
            ownership_scope_id=obj.ownership_scope_id,
            contribution_id=obj.contribution_id,
            number=2,
            base_revision_id=rev.id,
            title="bad",
            content_md="no typed metadata",
            created_by_user_id=user_id,
        )
        db.add(bad)
        db.flush()
        obj.current_revision_id = bad.id
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()


def test_concurrent_receipts_and_stale_revisions(pg_schema: tuple[Engine, Config, str]) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, scope_id = seed(engine)
    barrier = Barrier(2)

    def write() -> UUID:
        with Session(engine, expire_on_commit=False) as db:
            user = db.get(SqlUser, user_id)
            assert user

            def output(envelope: SqlContributionEnvelope) -> list[ContributionOutput]:
                obj, rev = create_object(
                    db,
                    project_id=project_id,
                    author=user,
                    kind=ResearchObjectKind.CLAIM,
                    title="once",
                    content_md="body",
                    rationale=None,
                    contribution=envelope,
                    commit=False,
                )
                return [ContributionOutput("OBJECT_REVISION", rev.id, scope_id)]

            barrier.wait(timeout=10)
            result = record_contribution(
                db,
                actor=human_actor(user_id),
                operation="create",
                idempotency_key="same",
                request_payload={"title": "once"},
                ownership_scope_id=scope_id,
                create_outputs=output,
            )
            return result.links[0].canonical_entity_id

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SqlResearchObject)) == 1
        assert db.scalar(select(func.count()).select_from(SqlMutationReceipt)) == 1
        rev = db.get(SqlObjectRevision, results[0])
        assert rev
        object_id = rev.object_id
    barrier = Barrier(2)

    def revise() -> str:
        with Session(engine) as db:
            user = db.get(SqlUser, user_id)
            assert user
            barrier.wait(timeout=10)
            try:
                create_revision(
                    db,
                    project_id=project_id,
                    object_id=object_id,
                    base_revision_id=results[0],
                    author=user,
                    title="next",
                    content_md="body",
                    rationale=None,
                )
                return "created"
            except StaleRevision:
                db.rollback()
                return "stale"

    with ThreadPoolExecutor(2) as pool:
        outcomes = list(pool.map(lambda _: revise(), range(2)))
    assert sorted(outcomes) == ["created", "stale"]


def test_outbox_payload_is_immutable_but_delivery_commits(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, _ = seed(engine)
    with Session(engine) as db:
        user = db.get(SqlUser, user_id)
        assert user
        create_object(
            db,
            project_id=project_id,
            author=user,
            kind=ResearchObjectKind.CLAIM,
            title="event",
            content_md="body",
            rationale=None,
        )
        events = claim_events(db, consumer_name="test")
        assert events
        first = events[0]
        record_consumer_receipt(
            db,
            event_id=first.id,
            consumer_name="test",
            success=True,
            claim_generation=first.attempts,
        )
        db.commit()
        with pytest.raises(DBAPIError):
            db.execute(text("UPDATE outbox_events SET payload='{}' WHERE id=:id"), {"id": first.id})
            db.commit()
        db.rollback()


def test_permanent_submission_numbers_backfill_and_concurrent_allocation(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "20260914_unified_deployment")
    _, _, scope_id = seed(engine)
    old_ids = [uuid4(), uuid4()]
    with engine.begin() as connection:
        for index, identity in enumerate(old_ids):
            connection.execute(
                text("""
                INSERT INTO research_activity_events
                (id, source_kind, source_id, ownership_scope_id, action, occurred_at, reconstructed)
                VALUES (:id, 'test', :id, :scope, 'object.created', :stamp, false)
            """),
                {"id": identity, "scope": scope_id, "stamp": utc_now() - timedelta(days=2 - index)},
            )
    command.upgrade(config, "head")
    with Session(engine) as db:
        assert list(
            db.scalars(
                select(SqlResearchActivityEvent.submission_number)
                .where(SqlResearchActivityEvent.id.in_(old_ids))
                .order_by(SqlResearchActivityEvent.occurred_at)
            )
        ) == [1, 2]
    barrier = Barrier(2)

    def write_event() -> int:
        with Session(engine, expire_on_commit=False) as db:
            row = SqlResearchActivityEvent(
                source_kind="test",
                source_id=uuid4(),
                ownership_scope_id=scope_id,
                action="object.created",
                occurred_at=utc_now(),
                reconstructed=False,
            )
            db.add(row)
            barrier.wait()
            db.commit()
            return row.submission_number

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.submit(write_event), pool.submit(write_event)
        assert sorted([first.result(timeout=10), second.result(timeout=10)]) == [3, 4]
    with Session(engine) as db:
        assert list(
            db.scalars(
                select(SqlResearchActivityEvent.submission_number)
                .where(SqlResearchActivityEvent.id.in_(old_ids))
                .order_by(SqlResearchActivityEvent.occurred_at)
            )
        ) == [1, 2]
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(
                text("UPDATE research_activity_events SET submission_number=999 WHERE id=:id"),
                {"id": old_ids[0]},
            )
            db.commit()
        db.rollback()

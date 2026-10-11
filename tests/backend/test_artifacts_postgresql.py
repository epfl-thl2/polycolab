"""Real row-lock, retry and commit/GC tests against the landed migration chain."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from datetime import datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_m0_postgresql import seed

from polycolab.artifacts import cleanup
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import ArtifactUploadDeclaration
from polycolab.db.models import SqlArtifact, SqlArtifactResearchLink, SqlUser
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ArtifactResearchRole, ArtifactState, ResearchObjectKind
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.research.objects import create_object
from polycolab.workspaces.service import DomainConflict


@pytest.fixture
def staged(pg_schema: tuple[Engine, Config, str]) -> tuple[Engine, UUID, UUID, UUID, UUID]:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, project_id, _ = seed(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = db.get(SqlUser, user_id)
        assert user is not None
        _, revision = create_object(
            db,
            project_id=project_id,
            author=user,
            kind=ResearchObjectKind.CLAIM,
            title="Artifact target",
            content_md="Exact target",
            rationale=None,
        )
        row = artifacts.reserve(
            db,
            project_id=project_id,
            user_id=user_id,
            declaration=ArtifactUploadDeclaration(sha256="0" * 64, byte_length=3),
            settings=Settings(),
        )
        artifacts.verified(db, project_id=project_id, user_id=user_id, artifact_id=row.id)
        return engine, user_id, project_id, revision.id, row.id


def test_concurrent_duplicate_attachments_create_one_link(
    staged: tuple[Engine, UUID, UUID, UUID, UUID],
) -> None:
    engine, user, project, revision, artifact = staged
    start = Barrier(2)

    def attach() -> UUID:
        with Session(engine) as db:
            start.wait(timeout=10)
            return artifacts.attach(
                db,
                project_id=project,
                user_id=user,
                artifact_id=artifact,
                revision_id=revision,
                role=ArtifactResearchRole.EVIDENCE,
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(attach), pool.submit(attach)
        assert first.result(timeout=15) == second.result(timeout=15)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SqlArtifactResearchLink)) == 1
        row = db.get(SqlArtifact, artifact)
        assert row is not None and row.state == ArtifactState.COMMITTED


def test_committed_attachment_keyset_query_on_postgresql(
    staged: tuple[Engine, UUID, UUID, UUID, UUID],
) -> None:
    engine, user, project, revision, artifact = staged
    with Session(engine) as db:
        links = [
            artifacts.attach(
                db,
                project_id=project,
                user_id=user,
                artifact_id=artifact,
                revision_id=revision,
                role=role,
            )
            for role in (ArtifactResearchRole.EVIDENCE, ArtifactResearchRole.SOURCE)
        ]
        first = artifacts.list_attachments(
            db, project_id=project, user_id=user, revision_id=revision, limit=1
        )
        assert len(first.items) == 1 and first.next_cursor is not None
        second = artifacts.list_attachments(
            db,
            project_id=project,
            user_id=user,
            revision_id=revision,
            limit=1,
            cursor=first.next_cursor,
        )
        assert [first.items[0].attachment_id, second.items[0].attachment_id] == sorted(links)
        assert second.next_cursor is None
        assert first.items[0].artifact.id == second.items[0].artifact.id == artifact
        assert first.items[0].artifact.state == ArtifactState.COMMITTED


def test_commit_and_gc_cannot_both_win(
    staged: tuple[Engine, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, user, project, revision, artifact = staged
    now = utc_now()
    # Reproduce operations on either side of expiry without sleeping an hour.
    clock: ContextVar[datetime] = ContextVar("artifact_test_clock", default=now)
    monkeypatch.setattr(artifacts, "utc_now", clock.get)
    monkeypatch.setattr(cleanup, "utc_now", clock.get)
    start = Barrier(2)

    def commit() -> bool:
        with Session(engine) as db:
            start.wait(timeout=10)
            try:
                artifacts.attach(
                    db,
                    project_id=project,
                    user_id=user,
                    artifact_id=artifact,
                    revision_id=revision,
                    role=ArtifactResearchRole.EVIDENCE,
                )
                return True
            except DomainConflict:
                return False

    def collect() -> list[UUID]:
        clock.set(now + timedelta(hours=2))
        with Session(engine) as db:
            start.wait(timeout=10)
            return [
                row.id for row in cleanup.claim_expired(SqlAlchemyTransaction(db), grace_seconds=0)
            ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer, collector = pool.submit(commit), pool.submit(collect)
        committed, collected = writer.result(timeout=15), collector.result(timeout=15)
    assert committed != (artifact in collected)
    with Session(engine) as db:
        row = db.get(SqlArtifact, artifact)
        assert row is not None
        assert row.state == (ArtifactState.COMMITTED if committed else ArtifactState.DELETING)
        count = db.scalar(select(func.count()).select_from(SqlArtifactResearchLink))
        assert count == (1 if committed else 0)


def test_gc_retries_tombstones_but_never_committed_artifacts(
    staged: tuple[Engine, UUID, UUID, UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, user, project, revision, artifact = staged
    with Session(engine) as db:
        artifacts.attach(
            db,
            project_id=project,
            user_id=user,
            artifact_id=artifact,
            revision_id=revision,
            role=ArtifactResearchRole.EVIDENCE,
        )
        second = artifacts.reserve(
            db,
            project_id=project,
            user_id=user,
            declaration=ArtifactUploadDeclaration(sha256="1" * 64, byte_length=3),
            settings=Settings(),
        )
    future = utc_now() + timedelta(hours=2)
    monkeypatch.setattr(cleanup, "utc_now", lambda: future)
    with Session(engine) as db:
        assert [
            row.id for row in cleanup.claim_expired(SqlAlchemyTransaction(db), grace_seconds=0)
        ] == [second.id]
        cleanup.deleted(SqlAlchemyTransaction(db), artifact_id=second.id)
        cleanup.deleted(SqlAlchemyTransaction(db), artifact_id=second.id)
        assert [
            row.id for row in cleanup.claim_expired(SqlAlchemyTransaction(db), grace_seconds=0)
        ] == [second.id]
        assert (
            cleanup.claim_expired(SqlAlchemyTransaction(db), grace_seconds=0, after=second.id) == []
        )

"""Opt-in catalogue acceptance using isolated schemas in disposable PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_catalogue_api import (
    formulation,
)
from test_catalogue_api import (
    test_catalogue_admission_revision_moderation_and_revocation as catalogue_journey,
)
from test_catalogue_api import (
    test_promotion_preserves_public_supporting_identity_and_denies_private as promotion_journey,
)
from test_m0_postgresql import seed

from polycolab.access.actors import human_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.catalogue import admission as catalogue
from polycolab.catalogue.schemas import CatalogueAdmit, CatalogueModerate, CatalogueRevise
from polycolab.db.models import (
    SqlCatalogueEntry,
    SqlCatalogueModerator,
    SqlCatalogueRevision,
    SqlObjectRevision,
    SqlResearchScope,
    SqlUser,
)
from polycolab.entities.enums import (
    ResearchScopeKind,
)
from polycolab.platform.config import Settings
from polycolab.workspaces.service import DomainConflict


def test_catalogue_real_postgresql_api(
    pg_schema: tuple[Engine, Config, str],
    identity_verifier: MappingIdentityVerifier,
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-catalogue-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            catalogue_journey(pg_client)
            promotion_journey(pg_client)
    finally:
        app.state.engine.dispose()


def test_catalogue_upgrade_preserves_research_and_protects_history(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "20260905_baseline")
    user_id, _, scope_id = seed(engine)
    with engine.begin() as db:
        # Seed the historical schema explicitly, not through evolving application
        # helpers that require metadata columns introduced by later migrations.
        old_revision_id = uuid4()
        values = {
            "user": user_id,
            "scope": scope_id,
            "contribution": uuid4(),
            "object": uuid4(),
            "id": old_revision_id,
        }
        db.execute(
            text(
                "INSERT INTO contribution_envelopes "
                "(id, actor_kind, human_user_id, ownership_scope_id, operation, "
                "source_event_cursors, created_at) VALUES "
                "(:contribution, 'HUMAN', :user, :scope, 'CREATE_OBJECT', '[]', now())"
            ),
            values,
        )
        db.execute(
            text(
                "INSERT INTO research_objects (id, ownership_scope_id, entity_class, kind, "
                "contribution_id, created_by_user_id, provenance_kind, created_at, updated_at) "
                "VALUES (:object, :scope, 'STATEMENT', 'CLAIM', :contribution, :user, "
                "'HUMAN_DIRECT', now(), now())"
            ),
            values,
        )
        db.execute(
            text(
                "INSERT INTO object_revisions (id, ownership_scope_id, object_id, schema_version, "
                "number, title, content_md, contribution_id, created_by_user_id, provenance_kind, "
                "created_at) VALUES (:id, :scope, :object, 1, 1, 'Before upgrade', 'Keep me', "
                ":contribution, :user, 'HUMAN_DIRECT', now())"
            ),
            values,
        )
        db.execute(
            text(
                "INSERT INTO statement_revisions (revision_id, kind, assumptions_md) "
                "VALUES (:id, 'CLAIM', 'Original assumptions')"
            ),
            values,
        )
        db.execute(
            text("UPDATE research_objects SET current_revision_id=:id WHERE id=:object"), values
        )
    command.upgrade(config, "head")
    settings = Settings()
    with Session(engine) as db:
        old = db.get(SqlObjectRevision, old_revision_id)
        assert old is not None and old.content_md == "Keep me"
        result = catalogue.mutate(
            db,
            actor=human_actor(user_id),
            settings=settings,
            idempotency_key="integrity",
            payload=CatalogueAdmit.model_validate(formulation()),
        )
    for sql in (
        "UPDATE catalogue_revisions SET source_version='tampered'",
        "DELETE FROM catalogue_revisions",
        "UPDATE catalogue_audit SET reason='tampered'",
        "DELETE FROM catalogue_audit",
        "DELETE FROM catalogue_entries",
    ):
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text(sql))
    with Session(engine) as db:
        assert db.get(SqlCatalogueRevision, result.revision_id) is not None
        # Private identities cannot be admitted by bypassing the domain.
        old = db.get(SqlObjectRevision, old_revision_id)
        assert old is not None
        db.add(
            SqlCatalogueEntry(
                id=old.object_id, official_revision_id=old.id, admitted_by_user_id=user_id
            )
        )
        with pytest.raises(DBAPIError):
            db.commit()
        db.rollback()


def test_catalogue_concurrent_admission_and_stale_edit(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    user_id, _, _ = seed(engine)
    settings = Settings()
    barrier = Barrier(2)

    def admit() -> dict[str, Any]:
        with Session(engine) as db:
            barrier.wait(timeout=5)
            return catalogue.mutate(
                db,
                actor=human_actor(user_id),
                settings=settings,
                idempotency_key="same",
                payload=CatalogueAdmit.model_validate(formulation()),
            ).model_dump()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: admit(), range(2)))
    assert results[0] == results[1]
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(SqlCatalogueEntry)) == 1
    barrier = Barrier(2)
    data = formulation()
    data.pop("kind")
    data["base_revision_id"] = results[0]["revision_id"]

    def revise(index: int) -> str:
        with Session(engine) as db:
            barrier.wait(timeout=5)
            try:
                catalogue.mutate(
                    db,
                    actor=human_actor(user_id),
                    settings=settings,
                    entry_id=results[0]["entry_id"],
                    idempotency_key=f"edit-{index}",
                    payload=CatalogueRevise.model_validate(data),
                )
                return "committed"
            except DomainConflict:
                return "stale"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(revise, range(2))) == ["committed", "stale"]


def test_catalogue_moderator_revocation_wins_against_waiting_mutation(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "head")
    owner_id, _, _ = seed(engine)
    settings = Settings()
    with Session(engine) as db:
        result = catalogue.mutate(
            db,
            actor=human_actor(owner_id),
            settings=settings,
            idempotency_key="admit",
            payload=CatalogueAdmit.model_validate(formulation()),
        )
        moderator = SqlUser(issuer="test", subject="moderator")
        db.add(moderator)
        db.flush()
        moderator_id = moderator.id
        db.add(SqlCatalogueModerator(user_id=moderator_id, active=True))
        db.commit()
    waiting = Event()

    def before_query(connection: Any, cursor: Any, statement: str, *args: Any) -> None:
        if "FROM research_scopes" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def hide() -> None:
        with Session(engine) as db:
            db.get(SqlCatalogueModerator, moderator_id)  # preload stale identity-map state
            event.listen(db.connection(), "before_cursor_execute", before_query)
            catalogue.mutate(
                db,
                actor=human_actor(moderator_id),
                settings=settings,
                entry_id=result.entry_id,
                idempotency_key="hide",
                payload=CatalogueModerate(
                    base_revision_id=result.revision_id, action="HIDE", reason="Pending report"
                ),
            )

    with Session(engine) as revoker, ThreadPoolExecutor(1) as pool:
        revoker.scalar(
            select(SqlResearchScope)
            .where(SqlResearchScope.scope_kind == ResearchScopeKind.COMMONS)
            .with_for_update()
        )
        assignment = revoker.get(SqlCatalogueModerator, moderator_id)
        assert assignment is not None
        assignment.active = False
        future = pool.submit(hide)
        try:
            assert waiting.wait(5)
        finally:
            revoker.commit()
        with pytest.raises(AuthorizationDenied):
            future.result(timeout=5)
    with Session(engine) as db:
        entry = db.get(SqlCatalogueEntry, result.entry_id)
        assert entry is not None and not entry.hidden

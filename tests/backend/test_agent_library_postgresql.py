"""Real database authority, immutability, migration, and publication concurrency."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_agent_library import (
    content,
    create,
    headers,
)
from test_agent_library import (
    test_archive_and_moderation_cover_every_public_path as moderation_journey,
)
from test_agent_library import (
    test_filter_pagination_and_retry_conflicts as listing_journey,
)
from test_agent_library import (
    test_private_public_versions_and_copy as publication_journey,
)
from test_agent_library import (
    test_skill_plugin_validation_and_download as skill_journey,
)
from test_agent_library import (
    test_unicode_and_quoted_tags_are_searchable as tags_journey,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.platform.config import Settings


@pytest.fixture
def library_pg(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> Iterator[TestClient]:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-library-web"), identity_verifier
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.engine.dispose()


def test_real_postgresql_library_journeys(library_pg: TestClient) -> None:
    publication_journey(library_pg)
    # Each journey expects an initially empty public list.


def test_real_postgresql_moderation(library_pg: TestClient) -> None:
    moderation_journey(library_pg)


def test_real_postgresql_skills(library_pg: TestClient) -> None:
    skill_journey(library_pg)


def test_real_postgresql_listing(library_pg: TestClient) -> None:
    listing_journey(library_pg)


def test_upgrade_parity_and_history(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "20261012_projects")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE library_upgrade_marker (value TEXT)"))
        db.execute(text("INSERT INTO library_upgrade_marker VALUES ('preserved')"))
    command.upgrade(config, "head")
    with engine.connect() as db:
        assert db.scalar(text("SELECT value FROM library_upgrade_marker")) == "preserved"
        differences = compare_metadata(MigrationContext.configure(db), Base.metadata)
        assert [
            change
            for change in differences
            if not (
                change[0] == "remove_table"
                and change[1].name in {"alembic_version", "library_upgrade_marker"}
            )
        ] == []
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-library-web"), identity_verifier
    )
    try:
        with TestClient(app) as client:
            draft = create(client)
            entry_id = draft["entry"]["id"]
            response = client.post(
                f"/api/v1/agent-library/{entry_id}/publish",
                json={"expected_revision": 1},
                headers=headers(),
            )
            assert response.status_code == 200
            version_id = response.json()["id"]
        for statement, params in (
            (
                "UPDATE agent_library_versions SET content = content WHERE id = :id",
                {"id": UUID(version_id)},
            ),
            ("DELETE FROM agent_library_versions WHERE id = :id", {"id": UUID(version_id)}),
            (
                "UPDATE agent_library_entries SET kind = 'PLUGIN' WHERE id = :id",
                {"id": UUID(entry_id)},
            ),
        ):
            with pytest.raises(DBAPIError):
                with engine.begin() as db:
                    db.execute(text(statement), params)
    finally:
        app.state.engine.dispose()


def test_concurrent_publication_and_retries(library_pg: TestClient) -> None:
    draft = create(library_pg)
    entry_id = draft["entry"]["id"]
    endpoint = f"/api/v1/agent-library/{entry_id}/publish"

    def publish(_: int) -> int:
        return int(
            library_pg.post(endpoint, json={"expected_revision": 1}, headers=headers()).status_code
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(publish, range(4)))
    assert statuses.count(200) == 1 and statuses.count(409) == 3
    draft = create(library_pg, data=content("Retry concurrently"))
    endpoint = f"/api/v1/agent-library/{draft['entry']['id']}/publish"
    same_key = headers()

    def retry(_: int) -> dict[str, Any]:
        result = library_pg.post(endpoint, json={"expected_revision": 1}, headers=same_key)
        assert result.status_code == 200
        return dict(result.json())

    with ThreadPoolExecutor(max_workers=4) as executor:
        versions = list(executor.map(retry, range(4)))
    assert len({version["id"] for version in versions}) == 1


def test_real_postgresql_tag_search(library_pg: TestClient) -> None:
    tags_journey(library_pg)

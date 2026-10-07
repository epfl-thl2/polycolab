"""Real PostgreSQL migration and immutable exact-version review acceptance."""

from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from test_m0_postgresql import pg_schema as pg_schema
from test_object_reviews import (
    test_external_reviews_require_opt_in_and_have_server_identity as external_reviews,
)
from test_object_reviews import (
    test_publication_explicitly_selects_reviews_and_closes_evidence as publish_reviews,
)
from test_object_reviews import (
    test_reviews_are_private_version_pinned_and_conflicts_remain_visible as version_reviews,
)

from polycolab.app.application import create_app
from polycolab.platform.config import Settings


def test_postgresql_object_reviews(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-test-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as real:
            version_reviews(real)
            external_reviews(real)
            publish_reviews(real)
        for statement in (
            "UPDATE object_reviews SET rationale = 'replaced'",
            "DELETE FROM object_reviews",
            "DELETE FROM review_evidence",
            "DELETE FROM publication_reviews",
        ):
            with engine.connect() as connection:
                with pytest.raises(DBAPIError, match="immutable"):
                    connection.execute(text(statement))
                connection.rollback()
    finally:
        app.state.engine.dispose()

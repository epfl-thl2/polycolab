"""Selective publication transaction evidence against migrated PostgreSQL."""

import test_publication
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.platform.config import Settings


def test_publication_transaction_and_history_are_postgresql_backed(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-publication-web"),
        identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            test_publication.test_preview_confirm_retry_and_historical_projection_are_exact_and_atomic(
                pg_client
            )
        with engine.begin() as connection:
            try:
                connection.execute(
                    text("UPDATE publication_manifests SET preview_digest = repeat('0', 64)")
                )
            except DBAPIError:
                pass
            else:
                raise AssertionError("immutable publication history accepted a mutation")
    finally:
        app.state.engine.dispose()

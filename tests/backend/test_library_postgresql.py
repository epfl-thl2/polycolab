"""The Library journey against the actual migration chain and PostgreSQL rules."""

from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from test_library_api import test_library_copy_is_independent_and_retry_safe as copy_journey
from test_library_api import (
    test_library_filters_before_pagination_and_preserves_historical_basis as discovery_journey,
)
from test_library_api import (
    test_library_import_and_iteration_preserve_exact_revisions as import_journey,
)
from test_library_api import (
    test_library_status_basis_is_attributable as basis_journey,
)
from test_m0_postgresql import pg_schema as pg_schema

from polycolab.app.application import create_app
from polycolab.platform.config import Settings


@pytest.mark.parametrize("visibility", ["PUBLIC", "PRIVATE"])
def test_library_copy_postgresql(
    pg_schema: tuple[Engine, Config, str], client: TestClient, visibility: str
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-library-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            copy_journey(pg_client, visibility)
    finally:
        app.state.engine.dispose()


def test_library_postgresql_journey(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-library-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            basis_journey(pg_client, literature=False, review=True)
            import_journey(pg_client, None)
    finally:
        app.state.engine.dispose()


def test_library_postgresql_discovery(
    pg_schema: tuple[Engine, Config, str], client: TestClient
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-library-web"),
        cast(Any, client.app).state.identity_verifier,
    )
    try:
        with TestClient(app) as pg_client:
            discovery_journey(pg_client)
    finally:
        app.state.engine.dispose()

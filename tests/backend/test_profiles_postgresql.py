from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from test_profiles import (
    test_profile_counts_public_authorship_and_sponsorship_only as verify_visibility,
)

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.platform.config import Settings


def test_public_profile_on_postgresql(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    _, config, url = pg_schema
    command.upgrade(config, "head")
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-profiles-web"), identity_verifier
    )
    try:
        with TestClient(app) as client:
            verify_visibility(client)
    finally:
        app.state.engine.dispose()

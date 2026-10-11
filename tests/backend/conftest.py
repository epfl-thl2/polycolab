from __future__ import annotations

import os
from collections.abc import Generator, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.platform.config import Environment, Settings, get_settings


@pytest.fixture
def identity_verifier() -> MappingIdentityVerifier:
    """Independent test identities without creating an application or database."""
    return MappingIdentityVerifier(
        {
            "owner": Principal("https://issuer.example", "owner", "owner@example.test", "Owner"),
            "contributor": Principal(
                "https://issuer.example",
                "contributor",
                "contributor@example.test",
                "Contributor",
            ),
            "reader": Principal(
                "https://issuer.example", "reader", "reader@example.test", "Reader"
            ),
            "outsider": Principal(
                "https://issuer.example", "outsider", "outsider@example.test", "Outsider"
            ),
            "same-email": Principal(
                "https://other.example", "same-email", "owner@example.test", "Same"
            ),
        }
    )


@pytest.fixture
def client(tmp_path: Path, identity_verifier: MappingIdentityVerifier) -> Generator[TestClient]:
    app = create_app(
        Settings(
            app_env=Environment.LOCAL,
            feature_agent_execution_enabled=True,
            database_url="sqlite+pysqlite:///:memory:",
            # API tests must not change behavior merely because a developer built
            # the sibling Vite application before running pytest.
            web_dist_dir=str(tmp_path / "missing-web-dist"),
        ),
        identity_verifier,
    )
    Base.metadata.create_all(app.state.engine)
    # Production migrations provision the singleton commons scope.
    from polycolab.db.models import ResearchScopeKind, SqlResearchScope

    with app.state.session_factory() as session:
        session.add(SqlResearchScope(scope_kind=ResearchScopeKind.COMMONS))
        session.commit()
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(app.state.engine)
    app.state.engine.dispose()


@pytest.fixture(autouse=True)
def isolated_dotenv(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Tests never inherit a developer's deployment file or cached settings."""
    from polycolab.platform.config import (
        VerificationControllerSettings,
        WorkerSettings,
        get_settings,
    )

    for model in (Settings, WorkerSettings, VerificationControllerSettings):
        monkeypatch.setitem(model.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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

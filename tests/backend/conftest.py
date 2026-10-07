from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.platform.config import Environment, Settings


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient]:
    app = create_app(
        Settings(
            app_env=Environment.LOCAL,
            feature_agent_execution_enabled=True,
            database_url="sqlite+pysqlite:///:memory:",
            # API tests must not change behavior merely because a developer built
            # the sibling Vite application before running pytest.
            web_dist_dir=str(tmp_path / "missing-web-dist"),
        ),
        MappingIdentityVerifier(
            {
                "owner": Principal(
                    "https://issuer.example", "owner", "owner@example.test", "Owner"
                ),
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
        ),
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

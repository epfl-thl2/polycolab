"""Public catalog, shared inference, and operator-only credential ownership."""

from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from test_conversations_api import create_project, create_session, send
from test_gateway import RecordingProvider, app_for, headers
from test_research_helper import Provider

from polycolab.db.models import SqlExecutionRateWindow, SqlProviderConnection
from polycolab.entities.time import utc_now
from polycolab.execution.limits import ExecutionLimitExceeded, purge_expired_rate_windows
from polycolab.model_gateway.catalog import ModelCatalog, load_catalog, reserve_budget, sync_catalog
from polycolab.model_gateway.service import (
    GrantInvalid,
    exchange_run_grant,
    issue_run_grant,
    request_model,
)
from polycolab.platform.config import Settings


def catalog_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("TEST_CATALOG_KEY", "platform-only-test-secret")
    path = tmp_path / "models.yaml"
    path.write_text("""providers:
  primary:
    base_url: https://8.8.8.8/v1
    api_key_env: TEST_CATALOG_KEY
    wire_api: chat_completions
models:
  - id: quick
    label: Polycolab Quick
    provider: primary
    model: quick-model
    uses: [research_helper, project_chat]
    harnesses: [platform]
    max_output_tokens: 1024
    input_microusd_per_million_tokens: 100000
    output_microusd_per_million_tokens: 200000
  - id: capable
    label: Polycolab Capable
    provider: primary
    model: capable-model
    uses: [research_helper]
    max_output_tokens: 2048
    input_microusd_per_million_tokens: 200000
    output_microusd_per_million_tokens: 400000
defaults:
  research_helper: quick
  project_chat: quick
daily_budget_microusd: 1000000000
""")
    return path


def install(client: TestClient, path: Path) -> ModelCatalog:
    app = app_for(client)
    catalog = load_catalog(str(path))
    app.state.settings.model_catalog = catalog
    app.state.session_factory.configure(
        info={
            "platform_model_ids": frozenset(
                model.id for model in catalog.models if "project_chat" in model.uses
            )
        }
    )
    with app.state.session_factory() as session:
        sync_catalog(session, catalog, app.state.credential_wrapper)
    return catalog


def test_catalog_loading_and_safe_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = catalog_file(tmp_path, monkeypatch)
    settings = Settings(polycolab_model_config=str(path))
    assert settings.research_helper_available
    assert settings.model_catalog.defaults.project_chat == "quick"
    assert "platform-only-test-secret" not in repr(settings.model_catalog)
    original = path.read_text()
    for invalid in (
        original.replace("provider: primary", "provider: missing"),
        original.replace("id: capable", "id: quick"),
        original.replace("project_chat: quick", "project_chat: capable"),
        original.replace("harnesses: [platform]", "harnesses: [codex]"),
        original.replace("https://8.8.8.8", "http://8.8.8.8"),
        original.replace("api_key_env: TEST_CATALOG_KEY", "api_key: unsafe-secret"),
    ):
        path.write_text(invalid)
        with pytest.raises(ValueError, match="invalid model catalog") as error:
            load_catalog(str(path))
        assert "unsafe-secret" not in str(error.value)
    path.write_text(original)
    monkeypatch.delenv("TEST_CATALOG_KEY")
    with pytest.raises(ValidationError, match="missing provider credential"):
        Settings(polycolab_model_config=str(path))


def test_shared_models_are_public_choices_but_not_editable_connections(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = install(client, catalog_file(tmp_path, monkeypatch))
    identifier = str(catalog.models[0].connection_id)
    assert client.get("/api/v1/platform-models").status_code == 401
    for token in ("owner", "outsider"):
        response = client.get("/api/v1/platform-models", headers=headers(token))
        assert response.status_code == 200
        assert response.json()[0]["default_for"] == ["research_helper", "project_chat"]
        assert response.json()[0]["id"] == identifier
        for private in ("api_key", "base_url", "TEST_CATALOG_KEY", "platform-only-test-secret"):
            assert private not in response.text
        assert (
            client.get("/api/v1/account/provider-connections", headers=headers(token)).json() == []
        )
        assert (
            client.delete(
                f"/api/v1/account/provider-connections/{identifier}", headers=headers(token)
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/account/provider-connections/{identifier}/rotate",
                headers=headers(token),
                json={"api_key": "replacement"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/account/provider-connections/{identifier}/validate",
                headers=headers(token),
            ).status_code
            == 404
        )
    project_id = str(create_project(client)["id"])
    conversation_id = str(create_session(client, project_id)["id"])
    request_id = str(uuid4())
    accepted = send(client, conversation_id, identifier, client_request_id=request_id)
    assert accepted.status_code == 202, accepted.text
    assert (
        send(client, conversation_id, identifier, client_request_id=request_id).status_code == 202
    )
    with app_for(client).state.session_factory() as session:
        budget = session.scalar(
            select(SqlExecutionRateWindow).where(SqlExecutionRateWindow.scope == "platform_budget")
        )
        assert budget is not None and budget.count > 0
    assert send(client, conversation_id, identifier, token="outsider").status_code == 404


def test_shared_gateway_secret_and_rotation(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = catalog_file(tmp_path, monkeypatch)
    catalog = install(client, path)
    app = app_for(client)
    user_id = UUID(client.get("/api/v1/account", headers=headers("owner")).json()["id"])
    model = catalog.models[0]
    run_id = uuid4()
    with app.state.session_factory() as session:
        token = issue_run_grant(
            session,
            user_id=user_id,
            provider_connection_id=model.connection_id,
            run_id=run_id,
            model_id=model.model,
            ttl_seconds=60,
            max_ttl_seconds=120,
        )
        provider = RecordingProvider()
        request_model(
            session,
            token=token,
            user_id=user_id,
            run_id=run_id,
            model_id=model.model,
            messages=[{"role": "user", "content": "Hello"}],
            max_output_tokens=128,
            wrapper=app.state.credential_wrapper,
            transport=cast(Any, provider),
            limits=app.state.gateway_limits,
        )
        assert provider.calls[0]["api_key"] == "platform-only-test-secret"
        token = issue_run_grant(
            session,
            user_id=user_id,
            provider_connection_id=model.connection_id,
            run_id=run_id,
            model_id=model.model,
            ttl_seconds=60,
            max_ttl_seconds=120,
        )
        sync_catalog(session, catalog, app.state.credential_wrapper)
        assert session.get(SqlProviderConnection, model.connection_id).credential_version == 1
    monkeypatch.setenv("TEST_CATALOG_KEY", "rotated-platform-secret")
    install(client, path)
    with app.state.session_factory() as session:
        with pytest.raises(GrantInvalid):
            exchange_run_grant(
                session, token=token, run_id=run_id, user_id=user_id, model_id=model.model
            )
        sync_catalog(session, ModelCatalog(), app.state.credential_wrapper)
        assert session.get(SqlProviderConnection, model.connection_id).deleted_at is not None
    install(client, path)
    with app.state.session_factory() as session:
        assert session.get(SqlProviderConnection, model.connection_id).deleted_at is None


def test_helper_selects_catalog_model_and_enforces_shared_budget(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = catalog_file(tmp_path, monkeypatch)
    install(client, path)
    app = app_for(client)
    provider = Provider()
    app.state.research_helper_transport = provider
    payload: dict[str, object] = {"messages": [{"role": "user", "content": "Compare approaches"}]}
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("owner"), json=payload
        ).status_code
        == 200
    )
    assert provider.calls[-1]["payload"]["model"] == "quick-model"
    payload["model_id"] = "capable"
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("owner"), json=payload
        ).status_code
        == 200
    )
    assert provider.calls[-1]["payload"]["model"] == "capable-model"
    payload["model_id"] = "missing"
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("owner"), json=payload
        ).status_code
        == 422
    )
    path.write_text(
        path.read_text().replace("daily_budget_microusd: 1000000000", "daily_budget_microusd: 1")
    )
    install(client, path)
    payload["model_id"] = "quick"
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("outsider"), json=payload
        ).status_code
        == 429
    )
    assert len(provider.calls) == 2


def test_daily_budget_survives_minute_counter_cleanup(client: TestClient) -> None:
    with app_for(client).state.session_factory() as session:
        reserve_budget(session, cost=7, limit=10)
        session.commit()
        purge_expired_rate_windows(session, retention=timedelta(seconds=1), now=utc_now())
        session.commit()
        with pytest.raises(ExecutionLimitExceeded):
            reserve_budget(session, cost=4, limit=10)
        session.rollback()


def test_catalog_startup_uses_migrated_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, identity_verifier: Any
) -> None:
    from polycolab.app.application import create_app
    from polycolab.operations.local_development import upgrade_database

    path = catalog_file(tmp_path, monkeypatch)
    database = tmp_path / "catalog.db"
    upgrade_database(database)
    settings = Settings(
        polycolab_model_config=str(path),
        database_url=f"sqlite+pysqlite:///{database}",
    )
    app = create_app(settings, identity_verifier)
    with TestClient(app) as browser:
        choices = browser.get("/api/v1/platform-models", headers=headers("owner"))
        assert choices.status_code == 200
        assert choices.json()[0]["harnesses"] == ["platform"]
        identifier = UUID(choices.json()[0]["id"])
        with app.state.session_factory() as session:
            connection = session.get(SqlProviderConnection, identifier)
            assert connection is not None and connection.user_id is None
            assert connection.encrypted_credential != b"platform-only-test-secret"
    # Unsetting configuration must deny old records, not silently fund known UUIDs.
    disabled = create_app(Settings(database_url=settings.database_url), identity_verifier)
    with TestClient(disabled) as browser:
        assert browser.get("/api/v1/platform-models", headers=headers("owner")).json() == []
        with disabled.state.session_factory() as session:
            from polycolab.model_gateway.catalog import connection_enabled

            connection = session.get(SqlProviderConnection, identifier)
            assert connection is not None and not connection_enabled(session, connection)
    app.state.engine.dispose()
    disabled.state.engine.dispose()


def test_shared_codex_broker_uses_platform_key_without_exposing_it(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_codex_runtime import response_bytes, spec

    from polycolab.db.models import SqlAgentRun

    path = catalog_file(tmp_path, monkeypatch)
    path.write_text(
        path.read_text()
        .replace("wire_api: chat_completions", "wire_api: responses")
        .replace("harnesses: [platform]", "harnesses: [platform, codex]")
    )
    catalog = install(client, path)
    app = app_for(client)
    app.state.settings.runtime_codex_image = spec().image
    worker_headers = {"Authorization": "Bearer polycolab-local-runtime-worker-token"}
    readiness = client.post(
        "/internal/v1/runtime/executors/readiness",
        headers=worker_headers,
        json={
            "worker_id": "catalog-codex",
            "engine": "codex",
            "image_digest": spec().image.rsplit(":", 1)[-1],
            "incarnation": "catalog-test",
            "slot_states": {"0": "AVAILABLE"},
            "capacity": 1,
        },
    )
    assert readiness.status_code == 204
    project = create_project(client)
    conversation = client.post(
        "/api/v1/conversations",
        headers=headers("owner"),
        json={
            "project_id": project["id"],
            "agent_kind": "RESEARCHER",
            "harness": "codex",
        },
    )
    assert conversation.status_code == 201
    accepted = send(client, conversation.json()["id"], str(catalog.models[0].connection_id))
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run"]["id"]
    with app.state.session_factory() as session:
        run = session.get(SqlAgentRun, UUID(run_id))
        assert run is not None and run.runtime_spec is not None
        assert run.runtime_spec["max_output_tokens"] == 1024
        assert run.runtime_spec["output_microusd_per_million_tokens"] == 200000
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers=worker_headers,
        json={
            "worker_id": "catalog-codex",
            "engine": "codex",
            "incarnation": "catalog-test",
            "slot_id": 0,
        },
    )
    assert claim.status_code == 200, claim.text
    assert "platform-only-test-secret" not in claim.text
    requests: list[dict[str, Any]] = []

    async def provider(**kwargs: Any) -> bytes:
        requests.append(kwargs)
        return response_bytes()

    app.state.hosted_provider_transport = provider
    result = client.post(
        f"/internal/v1/runtime/runs/{run_id}/responses",
        headers=worker_headers,
        json={
            "worker_id": "catalog-codex",
            "request_id": "catalog-model-request",
            "lease_generation": claim.json()["lease_generation"],
            "body": {"model": "quick-model", "stream": True, "input": "Hello"},
        },
    )
    assert result.status_code == 200, result.text
    assert requests[0]["api_key"] == "platform-only-test-secret"
    assert requests[0]["payload"]["max_output_tokens"] == 1024
    assert "platform-only-test-secret" not in result.text

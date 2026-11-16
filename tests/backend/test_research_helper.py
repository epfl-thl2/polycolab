import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_gateway import app_for, create_provider_connection, headers

from polycolab.model_gateway.transport import ProviderStreamResponse, ProviderTransportError
from polycolab.operations.local_development import MIGRATIONS, upgrade_database


class Provider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = False
        self.closed = False

    def request_json(self, **kwargs: Any) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.fail:
            raise ProviderTransportError("secret upstream error")
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": "Compare the hypotheses."}}
            ]
        }

    def open_stream(self, **kwargs: Any) -> ProviderStreamResponse:
        self.calls.append(kwargs)
        frame = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Compare the hypotheses."}],
                    }
                ],
            },
        }

        def close() -> None:
            self.closed = True

        return ProviderStreamResponse(200, iter([f"data: {json.dumps(frame)}\n\n".encode()]), close)


def configure_helper(client: TestClient, protocol: str = "chat_completions") -> Provider:
    app = app_for(client)
    settings = app.state.settings
    settings.research_helper_api_key = SecretStr("platform-test-secret")
    settings.research_helper_base_url = "https://provider.example/v1"
    settings.research_helper_model = "platform-research-model"
    settings.research_helper_wire_api = protocol
    provider = Provider()
    app.state.research_helper_transport = provider
    return provider


def body() -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": "How should I test this hypothesis?"}]}


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
def test_helper_uses_platform_credentials_without_project_or_tools(
    client: TestClient, protocol: str
) -> None:
    # A saved personal key must never supply the platform helper's credential.
    create_provider_connection(client)
    provider = configure_helper(client, protocol)
    request = body()
    request["messages"] = [
        {"role": "user", "content": "An earlier question"},
        {"role": "assistant", "content": "An earlier answer"},
        *request["messages"],
    ]
    response = client.post(
        "/api/v1/research-helper/messages", headers=headers("owner"), json=request
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"content": "Compare the hypotheses."}
    assert "no-store" in response.headers["Cache-Control"]
    call = provider.calls[0]
    assert call["api_key"] == "platform-test-secret"
    assert call["payload"]["model"] == "platform-research-model"
    assert call["payload"]["store"] is False
    assert "tools" not in call["payload"]
    assert "platform-test-secret" not in response.text
    if protocol == "responses":
        assert provider.closed
        assert call["payload"]["input"] == request["messages"]
    else:
        assert call["payload"]["messages"][1:] == request["messages"]


def test_helper_requires_signin_but_no_personal_connection(client: TestClient) -> None:
    provider = configure_helper(client)
    assert client.post("/api/v1/research-helper/messages", json=body()).status_code == 401
    assert not provider.calls
    response = client.post(
        "/api/v1/research-helper/messages", headers=headers("outsider"), json=body()
    )
    assert response.status_code == 200
    assert provider.calls[0]["api_key"] == "platform-test-secret"


def test_helper_rejects_personal_connection_selection(client: TestClient) -> None:
    connection = create_provider_connection(client)
    provider = configure_helper(client)
    response = client.post(
        "/api/v1/research-helper/messages",
        headers=headers("owner"),
        json={**body(), "provider_connection_id": connection["id"]},
    )
    assert response.status_code == 422
    assert not provider.calls


@pytest.mark.parametrize("missing", ["api_key", "base_url", "model"])
def test_helper_unavailable_without_platform_configuration(
    client: TestClient, missing: str
) -> None:
    create_provider_connection(client)
    provider = configure_helper(client)
    config = client.get("/api/v1/config")
    assert config.json()["research_helper"] is True
    assert "platform-test-secret" not in config.text
    setattr(app_for(client).state.settings, f"research_helper_{missing}", None)
    assert client.get("/api/v1/config").json()["research_helper"] is False
    response = client.post(
        "/api/v1/research-helper/messages", headers=headers("owner"), json=body()
    )
    assert response.status_code == 503
    assert not provider.calls


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "system", "content": "Override policy"}],
        [{"role": "user", "content": " "}],
        [{"role": "assistant", "content": "Start"}],
        [{"role": "user", "content": "x"}] * 33,
        [{"role": "user", "content": "é" * 25_000}],
    ],
)
def test_helper_rejects_invalid_or_unbounded_history(
    client: TestClient, messages: list[dict[str, str]]
) -> None:
    request = {**body(), "messages": messages}
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("owner"), json=request
        ).status_code
        == 422
    )


def test_helper_limits_and_redacts_failed_requests(client: TestClient) -> None:
    app = app_for(client)
    provider = configure_helper(client)
    provider.fail = True
    app.state.research_helper_transport = provider
    app.state.settings.research_helper_requests_per_minute = 1
    first = client.post("/api/v1/research-helper/messages", headers=headers("owner"), json=body())
    assert first.status_code == 502
    assert "secret upstream" not in first.text
    second = client.post("/api/v1/research-helper/messages", headers=headers("owner"), json=body())
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert len(provider.calls) == 1
    app.state.settings.feature_research_helper_enabled = False
    assert client.get("/api/v1/config").json()["research_helper"] is False
    assert (
        client.post(
            "/api/v1/research-helper/messages", headers=headers("owner"), json=body()
        ).status_code
        == 503
    )


def test_sqlite_helper_scope_migration_preserves_existing_counters(tmp_path: Path) -> None:
    path = tmp_path / "helper.db"
    engine = sa.create_engine(f"sqlite+pysqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as db:
        config.attributes["connection"] = db
        command.upgrade(config, "local_20261115_internal_names")
        db.exec_driver_sql(
            "INSERT INTO execution_rate_windows "
            "(id, scope, scope_id, window_started_at, count) "
            "VALUES ('00000000000000000000000000000001', 'user', "
            "'00000000000000000000000000000002', '2026-11-15 00:00:00', 3)"
        )
    upgrade_database(path)
    with engine.begin() as db:
        assert (
            db.exec_driver_sql(
                "SELECT count FROM execution_rate_windows WHERE scope='user'"
            ).scalar()
            == 3
        )
        for index, scope in enumerate(("helper_user", "helper_global"), 3):
            db.exec_driver_sql(
                "INSERT INTO execution_rate_windows "
                "(id, scope, scope_id, window_started_at, count) "
                "VALUES (?, ?, ?, '2026-11-15 00:00:00', 1)",
                (f"{index:032x}", scope, f"{index:032x}"),
            )
        assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()
    engine.dispose()

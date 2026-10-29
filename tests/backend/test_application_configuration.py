from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyUrl
from test_sessions_api import create_project
from workspace_support import headers

from polycolab.app.configuration import application_configuration
from polycolab.platform.config import Settings


def test_public_configuration_is_safe_and_follows_runtime_settings(
    client: TestClient,
) -> None:
    settings = cast(Any, client.app).state.settings
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert set(response.json()) == {
        "agent_execution",
        "email_recovery",
    }
    assert all(type(value) is bool for value in response.json().values())
    assert "private-operator" not in response.text
    settings.feature_agent_execution_enabled = False
    assert client.get("/api/v1/config").json()["agent_execution"] is False
    settings.feature_agent_execution_enabled = True
    assert client.get("/api/v1/config").json()["agent_execution"] is True


def test_execution_defaults_off_and_email_requires_delivery_configuration() -> None:
    settings = Settings()
    assert not application_configuration(settings).agent_execution
    assert not application_configuration(settings).email_recovery
    settings.smtp_host = "smtp.example"
    settings.smtp_from_address = "research@example.org"
    settings.public_app_origin = AnyUrl("https://research.example.org")
    assert application_configuration(settings).email_recovery


def test_workspace_agents_are_discoverable_without_enabling_hosted_execution(
    client: TestClient,
) -> None:
    settings = cast(Any, client.app).state.settings
    settings.feature_agent_execution_enabled = False
    available = client.get("/api/v1/platform-agents", headers=headers())
    assert available.status_code == 200
    assert {agent["version"] for agent in available.json()} == {3}
    project = create_project(client)
    response = client.post(
        "/api/v1/agent-sessions",
        headers=headers(),
        json={
            "project_id": project["id"],
            "agent_kind": "RESEARCHER",
            "agent_version": 3,
        },
    )
    assert response.status_code == 404


@pytest.mark.parametrize("visibility", [None, "PUBLIC", "PRIVATE"])
def test_project_creation_visibility(client: TestClient, visibility: str | None) -> None:
    body = {"name": "Visibility"}
    if visibility is not None:
        body["visibility"] = visibility
    response = client.post("/api/v1/projects", headers=headers(), json=body)
    assert response.status_code == 201
    assert response.json()["visibility"] == (visibility or "PUBLIC")

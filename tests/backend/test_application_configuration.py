from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyUrl
from test_public_external_agents import (
    create_human_claim,
    create_workspace,
    enable_research,
    headers,
    issue,
)

from polycolab.app.configuration import application_configuration
from polycolab.platform.config import Settings


def test_public_configuration_is_safe_and_follows_runtime_settings(client: TestClient) -> None:
    settings = cast(Any, client.app).state.settings
    settings.public_workspace_moderator_subjects = ["private-operator"]
    response = client.get("/api/v1/config")
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert set(response.json()) == {
        "agent_execution",
        "verification_submission",
        "verification_execution",
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


def test_version_two_agents_are_discoverable_without_enabling_hosted_execution(
    client: TestClient,
) -> None:
    settings = cast(Any, client.app).state.settings
    settings.feature_agent_execution_enabled = False
    available = client.get("/api/v1/platform-agents", headers=headers())
    assert available.status_code == 200
    assert {agent["version"] for agent in available.json()} == {1, 2}
    project = create_workspace(client)
    response = client.post(
        "/api/v1/agent-sessions",
        headers=headers(),
        json={"workspace_id": project["id"], "agent_kind": "RESEARCHER", "agent_version": 2},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("visibility", [None, "PUBLIC", "PRIVATE"])
def test_workspace_creation_visibility(client: TestClient, visibility: str | None) -> None:
    body = {"name": "Visibility"}
    if visibility is not None:
        body["visibility"] = visibility
    response = client.post("/api/v1/workspaces", headers=headers(), json=body)
    assert response.status_code == 201
    assert response.json()["visibility"] == (visibility or "PUBLIC")


def test_owner_visibility_changes_filter_research_and_history(client: TestClient) -> None:
    enable_research(client)
    project = create_workspace(client)
    claim = create_human_claim(client, project["id"], "Unique visibility research")
    credential = issue(client, project["id"])
    urls = [
        f"/api/v1/workspaces/{project['id']}",
        f"/api/v1/objects/{claim['id']}",
        f"/api/v1/versions/{claim['current_object_version_id']}",
    ]
    for visibility, anonymous_status in [("PRIVATE", 404), ("PUBLIC", 200), ("PRIVATE", 404)]:
        path = f"/api/v1/workspaces/{project['id']}"
        assert (
            client.patch(
                path, headers=headers("outsider"), json={"visibility": visibility}
            ).status_code
            == 404
        )
        changed = client.patch(path, headers=headers(), json={"visibility": visibility})
        assert changed.status_code == 200
        for url in urls:
            assert client.get(url).status_code == anonymous_status
            assert client.get(url, headers=headers()).status_code == 200
            assert client.get(url, headers=headers(credential["secret"])).status_code == 200
        activity = client.get("/api/v1/activity", params={"workspace_id": project["id"]})
        assert activity.status_code == 200
        assert bool(activity.json()["items"]) is (visibility == "PUBLIC")
        workspaces = client.get("/api/v1/workspaces", params={"scope": "public"}).json()["items"]
        assert any(row["id"] == project["id"] for row in workspaces) is (visibility == "PUBLIC")


def test_private_workspace_search_preserves_access_boundaries(client: TestClient) -> None:
    project = client.post(
        "/api/v1/workspaces",
        headers=headers(),
        json={"name": "Private only", "visibility": "PRIVATE"},
    ).json()
    claim = create_human_claim(client, project["id"], "Private searchable claim")
    params = {"scope": "member", "workspace_id": project["id"], "q": "searchable"}
    response = client.get("/api/v1/discovery", headers=headers(), params=params)
    assert response.status_code == 200
    assert response.json()["items"][0]["object_version"]["object_id"] == claim["id"]
    assert client.get("/api/v1/discovery", params=params).status_code == 401
    public = client.get("/api/v1/discovery", params={"q": "searchable"})
    assert public.status_code == 200
    assert public.json()["items"] == []

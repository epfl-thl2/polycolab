"""Fresh baseline API and metadata acceptance."""

from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import select

from polycolab.db.models import (
    SqlObjectRevision,
    SqlResearchObject,
    SqlResearchScope,
    SqlStatementRevision,
)


def test_new_project_research_has_typed_revision_and_scope(client: TestClient) -> None:
    headers = {"Authorization": "Bearer owner"}
    project = client.post(
        "/api/v1/workspaces", headers=headers, json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    response = post_research(
        client,
        "/api/v1/objects",
        headers=headers,
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    "title": "Claim",
                    "content_md": "body",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                },
                "structural_relationships": [],
            },
        },
    )
    assert response.status_code == 201
    with cast(Any, client.app).state.session_factory() as db:
        obj = db.get(SqlResearchObject, UUID(response.json()["id"]))
        scope = db.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == UUID(project["id"]))
        )
        assert obj and scope and obj.ownership_scope_id == scope.id
        assert obj.entity_class.value == "STATEMENT"
        assert db.get(SqlStatementRevision, obj.current_revision_id)
        assert (
            db.get(SqlObjectRevision, obj.current_revision_id).contribution_id
            == obj.contribution_id
        )
        assert "workspace_id" not in SqlResearchObject.__table__.columns


def test_private_workspace_reads_require_membership_until_owner_shares(client: TestClient) -> None:
    headers = {"Authorization": "Bearer owner"}
    project = client.post(
        "/api/v1/workspaces", headers=headers, json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    created = post_research(
        client,
        "/api/v1/objects",
        headers=headers,
        json={
            "destination": {"kind": "workspace", "workspace_id": project["id"]},
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    "title": "Secret",
                    "content_md": "Private draft",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                },
                "structural_relationships": [],
            },
        },
    ).json()
    routes = (
        f"/api/v1/workspaces/{project['id']}",
        f"/api/v1/workspaces/{project['id']}/objects",
        f"/api/v1/objects/{created['id']}",
        f"/api/v1/objects/{created['id']}/versions",
        f"/api/v1/versions/{created['current_object_version_id']}",
        f"/api/v1/objects/{created['id']}/relations",
    )
    for route in routes:
        response = client.get(route)
        assert response.status_code == 404
        assert "Private draft" not in response.text
    assert (
        client.patch(
            f"/api/v1/workspaces/{project['id']}", headers=headers, json={"visibility": "PUBLIC"}
        ).status_code
        == 200
    )
    responses = []
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, (route, response.text)
        responses.append(response.json())
    workspace, objects, obj, versions, version, relations = responses
    assert workspace["id"] == project["id"]
    assert [item["id"] for item in objects["items"]] == [created["id"]]
    assert obj["id"] == created["id"]
    assert [item["id"] for item in versions["items"]] == [created["current_object_version_id"]]
    assert version["id"] == created["current_object_version_id"]
    assert version["content"]["content_md"] == "Private draft"
    assert relations["items"] == []

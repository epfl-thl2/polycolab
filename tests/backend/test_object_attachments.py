"""Object attachment identity is independent of an attempt's worked-on version."""

from typing import Any

from fastapi.testclient import TestClient
from test_catalogue_api import enable
from test_research_domain import create_object, create_project, headers


def test_note_uuid_attachment_survives_parent_version_and_checks_privacy(
    client: TestClient,
) -> None:
    enable(client)
    project = create_project(client)
    parent = create_object(client, project)
    content: dict[str, Any] = {
        "title": "Persistent note",
        "content_md": "A useful observation",
        "assumptions_md": "None",
        "reported_outcome": None,
        "explanation_md": None,
        "attached_object_ids": [parent["id"]],
    }
    body: dict[str, Any] = {
        "destination": {"kind": "project", "project_id": project},
        "snapshot": {"kind": "NOTE", "content": content, "structural_relationships": []},
    }
    response = client.post("/api/v1/objects", headers=headers("owner"), json=body)
    assert response.status_code == 201, response.text
    version = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    edited = client.post(
        f"/api/v1/objects/{parent['id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": parent["current_object_version_id"],
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **parent["current_object_version"]["content"],
                    "title": "Updated parent",
                },
                "structural_relationships": [],
            },
        },
    )
    assert edited.status_code == 201, edited.text
    saved = client.get(f"/api/v1/versions/{version}", headers=headers("owner")).json()
    assert saved["content"]["attached_object_ids"] == [parent["id"]]
    preview = client.post(
        "/api/v1/publication/preview",
        headers=headers("owner"),
        json={"project_id": project, "object_version_ids": [version]},
    )
    assert preview.status_code == 200, preview.text
    current = next(
        row["entity_id"]
        for row in edited.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    assert current in preview.json()["required_object_version_ids"]
    other = create_project(client)
    body["destination"]["project_id"] = other
    denied = client.post("/api/v1/objects", headers=headers("owner"), json=body)
    assert denied.status_code == 404, denied.text


def test_attempt_exposes_object_attachment_and_retains_exact_work_target(
    client: TestClient,
) -> None:
    project = create_project(client)
    attempt = create_object(client, project, kind="ATTEMPT")
    version = attempt["current_object_version"]
    target = next(
        pin["target_object_version_id"]
        for pin in version["structural_relationships"]
        if pin["relationship_type"] == "TARGET"
    )
    parent = client.get(f"/api/v1/versions/{target}", headers=headers("owner")).json()
    assert version["content"]["attached_object_ids"] == [parent["object_id"]]
    assert target != parent["object_id"]


def test_formalization_requires_version_attachment_not_object_attachment(
    client: TestClient,
) -> None:
    project = create_project(client)
    parent = create_object(client, project, kind="NOTE")
    content = {
        "title": "Formalization",
        "content_md": "theorem example : True := by trivial",
        "assumptions_md": "None",
        "reported_outcome": None,
        "explanation_md": None,
    }
    body = {
        "destination": {"kind": "project", "project_id": project},
        "snapshot": {
            "kind": "FORMALIZATION",
            "content": {**content, "attached_object_ids": [parent["id"]]},
            "structural_relationships": [],
        },
    }
    invalid = client.post("/api/v1/objects", headers=headers("owner"), json=body)
    assert invalid.status_code == 422, invalid.text
    response = client.post(
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "destination": body["destination"],
            "snapshot": {
                "kind": "FORMALIZATION",
                "content": content,
                "structural_relationships": [
                    {
                        "relationship_type": "ATTACHMENT",
                        "target_object_version_id": parent["current_object_version_id"],
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    version = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    exact = client.get(f"/api/v1/versions/{version}", headers=headers("owner")).json()
    assert not exact["content"].get("attached_object_ids")
    assert (
        exact["structural_relationships"][0]["target_object_version_id"]
        == parent["current_object_version_id"]
    )

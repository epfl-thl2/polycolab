"""Declarations have visibility and attribution independent of their endpoints."""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_catalogue_api import admit, enable, headers
from test_research_domain import create_object, create_workspace

from polycolab.db.models import SqlResearchScope
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.entities.research import BidirectionalRelationship


def test_private_equivalence_between_public_versions(
    client: TestClient,
) -> None:
    app = enable(client)
    workspace = create_workspace(client)
    first, second = admit(client, "equivalence-first"), admit(client, "equivalence-second")
    body = {
        "destination": {"kind": "workspace", "workspace_id": workspace},
        "direction": "BIDIRECTIONAL",
        "first_object_version_id": first["object_version_id"],
        "second_object_version_id": second["object_version_id"],
        "relationship_type": "EQUIVALENT_TO",
        "description": "Our workspace's declaration, not endorsement by either endpoint",
    }
    response = client.post("/api/v1/relations", headers=headers(key="equivalence"), json=body)
    assert response.status_code == 201, response.text
    assert client.post(
        "/api/v1/relations", headers=headers(key="equivalence"), json=body
    ).json() == {**response.json(), "replayed": True}
    relation_id = response.json()["outputs"][0]["entity_id"]
    with app.state.session_factory() as session:
        scope = session.scalar(
            select(SqlResearchScope).where(SqlResearchScope.project_id == UUID(workspace))
        )
        row = session.get(SqlObjectVersionRelationship, UUID(relation_id))
        assert row is not None and scope is not None
        assert row.ownership_scope_id == scope.id
        assert row.source_object_version_id is None and row.target_object_version_id is None
        assert [row.first_object_version_id, row.second_object_version_id] == sorted(
            (UUID(first["object_version_id"]), UUID(second["object_version_id"]))
        )
        snapshot = SqlResearchReadStore(session).relationships([row.id])[row.id]
    assert isinstance(snapshot, BidirectionalRelationship)
    assert snapshot.ownership_scope_id == scope.id
    assert not hasattr(snapshot, "source_object_version_id")
    for endpoint in (first, second):
        path = f"/api/v1/versions/{endpoint['object_version_id']}/relationships"
        public = client.get(path)
        assert public.status_code == 200 and public.json() == []
        private = client.get(path, headers=headers(), params={"workspace_id": workspace})
        assert private.status_code == 200, private.text
        assert [row["id"] for row in private.json()] == [relation_id]
        assert (
            client.get(
                path, headers=headers("outsider"), params={"workspace_id": workspace}
            ).status_code
            == 404
        )
        public_graph = client.get(f"/api/v1/objects/{endpoint['entry_id']}/relations")
        assert public_graph.status_code == 200
        assert relation_id not in public_graph.text

    rejected = client.post(
        "/api/v1/relations",
        headers=headers(key="directed-not-local"),
        json={
            "destination": body["destination"],
            "direction": "UNIDIRECTIONAL",
            "source_object_version_id": first["object_version_id"],
            "target_object_version_id": second["object_version_id"],
            "relationship_type": "DEPENDS_ON",
            "description": "Must originate locally",
        },
    )
    assert rejected.status_code == 403


def test_declaration_cannot_reference_another_workspaces_private_version(
    client: TestClient,
) -> None:
    enable(client)
    destination, other = create_workspace(client), create_workspace(client)
    public = admit(client)
    private = create_object(client, other)
    response = client.post(
        "/api/v1/relations",
        headers=headers(key="private-target"),
        json={
            "destination": {"kind": "workspace", "workspace_id": destination},
            "direction": "BIDIRECTIONAL",
            "first_object_version_id": public["object_version_id"],
            "second_object_version_id": private["current_object_version_id"],
            "relationship_type": "EQUIVALENT_TO",
            "description": "Must not cross a private workspace boundary",
        },
    )
    assert response.status_code == 404

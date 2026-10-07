from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable
from test_shared_agent_api import body, headers, setup


def test_route_inventory_has_no_public_namespace_or_duplicate_operations(
    client: TestClient,
) -> None:
    routes = [
        route
        for route in iter_route_contexts(cast(Any, client.app).routes)
        if isinstance(route.original_route, APIRoute)
    ]
    pairs = [(route.path, method) for route in routes for method in route.methods or set()]
    assert len(pairs) == len(set(pairs))
    assert all("public" not in (route.path or "").split("/") for route in routes)
    schema = client.get("/api/openapi.json").json()
    for path in ["/api/v1/catalogue", "/api/v1/discovery", "/api/v1/records"]:
        assert {} in schema["paths"][path]["get"]["security"]
        assert {"ExternalAgentBearer": []} in schema["paths"][path]["get"]["security"]
    assert {} not in schema["paths"]["/api/v1/catalogue"]["post"]["security"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/public/library",
        "/api/v1/public/catalogue",
        "/api/v1/public/records",
        "/api/v1/public/discovery",
        "/public/workspaces",
        "/public/catalogue/example",
        "/public/records/example",
    ],
)
def test_removed_urls_do_not_redirect(client: TestClient, path: str) -> None:
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 404
    assert "location" not in response.headers


def test_public_and_member_reads_share_routes_without_sharing_private_data(
    client: TestClient,
) -> None:
    enable(client)
    entry = admit(client)
    workspace, secret = setup(client)
    created = client.post(
        "/api/v1/objects", headers=headers(secret), json=body(workspace["id"])
    ).json()
    object_id, revision_id = [row["entity_id"] for row in created["outputs"]]
    for path in [
        "/api/v1/library",
        "/api/v1/catalogue",
        "/api/v1/discovery",
        "/api/v1/records",
        f"/api/v1/catalogue/{entry['entry_id']}",
        f"/api/v1/assurance/{entry['object_version_id']}",
        f"/api/v1/research/objects/{entry['entry_id']}/attempts",
    ]:
        for auth in [{}, headers(secret), headers("owner")]:
            assert client.get(path, headers=auth).status_code == 200, path
        assert client.get(path, headers=headers("invalid-explicit-token")).status_code == 401
    exact = f"/api/v1/records/{revision_id}"
    assert client.get(exact).status_code == 404
    assert client.get(exact, headers=headers("outsider")).status_code == 404
    assert client.get(exact, headers=headers(secret)).status_code == 200
    assert (
        client.get(
            exact, headers=headers(secret), params={"workspace_id": str(uuid4())}
        ).status_code
        == 404
    )
    for path in ["/api/v1/records", "/api/v1/discovery"]:
        params = {"scope": "member", "workspace_id": workspace["id"]}
        assert client.get(path, params=params).status_code == 401
        assert client.get(path, params=params, headers=headers("outsider")).status_code in (
            403,
            404,
        )
        response = client.get(path, params=params, headers=headers(secret))
        assert response.status_code == 200, response.text
        assert object_id in response.text
        assert revision_id not in client.get(path).text

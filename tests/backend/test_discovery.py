"""Search filters apply before page boundaries and never include private activity."""

from uuid import UUID

from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, headers
from test_library_api import attempt_payload

from polycolab.db.models import SqlCatalogueEntry


def test_search_finds_failed_attempts_and_filters_private_and_hidden(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    project = client.post(
        "/api/v1/projects", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    for key, scope in (("public", None), ("private", project["id"])):
        payload = attempt_payload(entry["object_version_id"], project_id=scope)
        payload["snapshot"]["content"].update(
            reported_outcome="FAILED", explanation_md="A stronger hypothesis is needed"
        )
        response = client.post(
            "/api/v1/objects",
            headers=headers(key=key),
            json=payload,
        )
        assert response.status_code == 201, response.text
    found = client.get("/api/v1/discovery", params={"q": "induction", "status": "FAILED"})
    assert found.status_code == 200, found.text
    assert len(found.json()["items"]) == 1
    assert found.json()["items"][0]["object_version"]["content"]["reported_outcome"] == "FAILED"
    private = client.get(
        "/api/v1/discovery",
        headers=headers(),
        params={"scope": "member", "project_id": project["id"], "q": "induction"},
    )
    assert len(private.json()["items"]) == 1
    assert client.get(
        "/api/v1/discovery",
        headers=headers("outsider"),
        params={"scope": "member", "project_id": project["id"]},
    ).status_code in (403, 404)
    first = client.get("/api/v1/discovery", params={"limit": 1}).json()
    source_result = client.get("/api/v1/discovery", params={"q": "Conjecture"}).json()
    assert source_result["items"][0]["catalogue_entry_id"] == entry["entry_id"]
    second = client.get(
        "/api/v1/discovery", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert first["items"][0]["object_version"]["id"] != second["items"][0]["object_version"]["id"]
    assert (
        client.get("/api/v1/discovery", params={"kind": "STATEMENT"}).json()["items"][0][
            "catalogue_entry_id"
        ]
        == entry["entry_id"]
    )
    with app.state.session_factory() as db:
        value = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert value is not None
        value.hidden = True
        db.commit()
    assert client.get("/api/v1/discovery", params={"q": "induction"}).json()["items"] == []


def test_anonymous_project_search_filters_scope_and_private_records(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    projects = []
    for index, visibility in enumerate(["PUBLIC", "PUBLIC", "PRIVATE"]):
        project = client.post(
            "/api/v1/projects",
            headers=headers(),
            json={"visibility": visibility, "name": f"Project {index}"},
        ).json()
        projects.append(project["id"])
        response = client.post(
            "/api/v1/objects",
            headers=headers(key=f"scoped-record-{index}"),
            json=attempt_payload(entry["object_version_id"], project_id=project["id"]),
        )
        assert response.status_code == 201, response.text
    for project_id in projects[:2]:
        response = client.get(
            "/api/v1/discovery", params={"project_id": project_id, "q": "induction"}
        )
        assert response.status_code == 200, response.text
        hits = response.json()["items"]
        assert len(hits) == 1
        exact = client.get(f"/api/v1/records/{hits[0]['object_version']['id']}")
        assert exact.status_code == 200, exact.text
    private = client.get("/api/v1/discovery", params={"project_id": projects[2]})
    assert private.status_code == 200
    assert private.json()["items"] == []
    assert (
        client.get(
            "/api/v1/discovery", params={"scope": "member", "project_id": projects[0]}
        ).status_code
        == 401
    )

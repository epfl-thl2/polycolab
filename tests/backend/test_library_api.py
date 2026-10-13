"""Library admission, discovery and revision-pinned project development."""

from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_catalogue_api import admit, enable, formulation, headers
from test_public_external_agents import version_snapshot

from polycolab.catalogue import projections
from polycolab.db.models import ProjectVisibility, SqlCatalogueEntry, SqlProject
from polycolab.research.objects import ResearchNotFound
from polycolab.research.version_projections import version_reads


@pytest.mark.parametrize("path", ["/api/v1/library", "/api/v1/catalogue"])
def test_public_catalogue_page_batches_version_projections(client: TestClient, path: str) -> None:
    app = enable(client)
    for index in range(8):
        admit(client, f"batch-{index}")
    queries: list[str] = []

    def record_query(*args: Any) -> None:
        queries.append(args[2])

    event.listen(app.state.engine, "before_cursor_execute", record_query)
    try:
        single = client.get(path, params={"limit": 1})
        assert single.status_code == 200, single.text
        single_count = len(queries)
        queries.clear()
        page = client.get(path, params={"limit": 8})
        assert page.status_code == 200, page.text
        assert len(page.json()["items"]) == 8
        assert len(queries) <= single_count + 1
        assert page.json()["items"][0] == single.json()["items"][0]
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record_query)


@pytest.mark.parametrize("path", ["/api/v1/library", "/api/v1/catalogue"])
def test_catalogue_batch_rechecks_an_entry_hidden_during_projection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    enable(client)
    hidden = admit(client, "hidden-during-projection")
    visible = admit(client, "still-visible")
    batch_seen = False

    def project(session: Any, versions: Any, **kwargs: Any) -> Any:
        nonlocal batch_seen
        if len(versions) > 1:
            assert not batch_seen
            batch_seen = True
            entry = session.get(SqlCatalogueEntry, UUID(hidden["entry_id"]))
            assert entry is not None
            entry.hidden = True
            session.flush()
            raise ResearchNotFound
        return version_reads(session, versions, **kwargs)

    monkeypatch.setattr(projections, "version_reads", project)
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert batch_seen
    assert [item["entry_id"] for item in response.json()["items"]] == [visible["entry_id"]]


def attempt_payload(object_version_id: str, project_id: str | None = None) -> dict[str, Any]:
    snapshot = version_snapshot("ATTEMPT", "Failed induction", "The induction does not close.")
    snapshot["content"].update(outcome="FAILED", findings_md="A stronger hypothesis is needed")
    snapshot["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": object_version_id}
        for role in ("ATTACHMENT", "TARGET")
    ]
    return {
        "destination": (
            {"kind": "project", "project_id": project_id}
            if project_id
            else {"kind": "library", "statement_object_version_id": object_version_id}
        ),
        "snapshot": snapshot,
    }


def test_library_reads_are_available_and_preserve_write_authority(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    paths = [
        "/api/v1/library",
        f"/api/v1/catalogue/{entry['entry_id']}/history",
        f"/api/v1/catalogue/{entry['entry_id']}/versions/{entry['object_version_id']}",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
    assert client.post("/api/v1/catalogue", json=formulation()).status_code == 401


@pytest.mark.parametrize("literature,review", [(True, False), (False, True), (True, True)])
def test_library_status_basis_is_attributable(
    client: TestClient, literature: bool, review: bool
) -> None:
    enable(client)
    payload = formulation()
    payload["reported_status"] = "Conjectured"
    if not literature:
        payload["source"] = None
    if review:
        payload["review_rationale"] = "I checked the assumptions and the unresolved status."
    response = client.post(
        "/api/v1/catalogue", headers=headers(key=f"basis-{literature}-{review}"), json=payload
    )
    assert response.status_code == 201, response.text
    entry = client.get(f"/api/v1/catalogue/{response.json()['entry_id']}").json()
    assert bool(entry["source"]) is literature
    assert bool(entry["review_rationale"]) is review
    assert bool(entry["reviewer_display_name"]) is review
    assert bool(entry["reviewed_at"]) is review
    assert entry["object_version"]["number"] == 1
    assert client.get(f"/api/v1/records/{response.json()['object_version_id']}").status_code == 200


def test_library_rejects_missing_basis_and_forged_review_identity(client: TestClient) -> None:
    enable(client)
    for extra in (
        {"source": None},
        {"source": None, "review_rationale": "   "},
        {"reviewer_display_name": "Someone else"},
        {"reviewed_at": "2020-01-01"},
    ):
        response = client.post(
            "/api/v1/catalogue", headers=headers(), json={**formulation(), **extra}
        )
        assert response.status_code == 422, response.text


def test_library_filters_before_pagination_and_preserves_historical_basis(
    client: TestClient,
) -> None:
    app = enable(client)
    original = admit(client)
    reviewed = client.post(
        "/api/v1/catalogue",
        headers=headers(key="reviewed"),
        json={
            **formulation(),
            "title": "Reviewed compactness",
            "source": None,
            "reported_status": "Open",
            "review_rationale": "Checked formulation and open status.",
        },
    ).json()
    record = client.post(
        "/api/v1/objects",
        headers=headers(key="attempt"),
        json=attempt_payload(original["object_version_id"]),
    )
    assert record.status_code == 201, record.text
    result = client.get("/api/v1/library", params={"basis": "review", "limit": 1}).json()
    assert [item["entry_id"] for item in result["items"]] == [reviewed["entry_id"]]
    assert result["next_cursor"] is None
    assert len(client.get("/api/v1/library", params={"q": "positive integer"}).json()["items"]) == 2
    first = client.get("/api/v1/library", params={"limit": 1}).json()
    assert first["items"][0]["entry_id"] == reviewed["entry_id"]
    second = client.get(
        "/api/v1/library", params={"limit": 1, "cursor": first["next_cursor"]}
    ).json()
    assert [item["entry_id"] for item in second["items"]] == [original["entry_id"]]
    assert client.get("/api/v1/library", params={"cursor": "invalid"}).status_code == 422
    assert client.get("/api/v1/library", params={"kind": "ATTEMPT"}).status_code == 422
    changed = client.post(
        f"/api/v1/catalogue/{original['entry_id']}/versions",
        headers=headers(key="revise"),
        json={
            **{k: v for k, v in formulation().items() if k != "kind"},
            "expected_current_object_version_id": original["object_version_id"],
            "source": None,
            "review_rationale": "A new human review.",
            "reported_status": "Established",
        },
    )
    assert changed.status_code == 201, changed.text
    history = client.get(f"/api/v1/catalogue/{original['entry_id']}/history").json()
    assert len(history["items"]) == 2
    assert history["items"][0]["review_rationale"] == "A new human review."
    assert history["items"][1]["source"]["identifier"] == formulation()["source"]["identifier"]
    assert history["items"][1]["review_rationale"] is None
    with app.state.session_factory() as db:
        entry = db.get(SqlCatalogueEntry, UUID(original["entry_id"]))
        assert entry is not None
        entry.hidden = True
        db.commit()
    assert len(client.get("/api/v1/library").json()["items"]) == 1
    assert client.get(f"/api/v1/catalogue/{original['entry_id']}/history").status_code == 404
    assert (
        client.get(
            f"/api/v1/catalogue/{original['entry_id']}/versions/{original['object_version_id']}"
        ).status_code
        == 404
    )


@pytest.mark.parametrize("visibility", [None, "PUBLIC", "PRIVATE"])
def test_library_import_and_iteration_preserve_exact_revisions(
    client: TestClient, visibility: str | None
) -> None:
    app = enable(client)
    entry = admit(client)
    body = {
        "object_version_id": entry["object_version_id"],
        "create_new_project": True,
        "project_name": "Library investigation",
    }
    if visibility is not None:
        body["project_visibility"] = visibility
    response = client.post("/api/v1/project-references", headers=headers(key="import"), json=body)
    assert response.status_code == 201, response.text
    pin = response.json()
    assert (
        client.post("/api/v1/project-references", headers=headers(key="import"), json=body).json()
        == pin
    )
    with app.state.session_factory() as db:
        project = db.get(SqlProject, UUID(pin["project_id"]))
        assert project is not None and project.visibility == ProjectVisibility(
            visibility or "PUBLIC"
        )
    existing = {
        "object_version_id": entry["object_version_id"],
        "project_id": pin["project_id"],
    }
    assert (
        client.post(
            "/api/v1/project-references", headers=headers(key="existing"), json=existing
        ).json()["id"]
        == pin["id"]
    )
    assert client.post(
        "/api/v1/project-references", headers=headers("outsider", key="denied"), json=existing
    ).status_code in (403, 404)
    attempt = client.post(
        "/api/v1/objects",
        headers=headers(key="research"),
        json=attempt_payload(entry["object_version_id"], project_id=pin["project_id"]),
    )
    assert attempt.status_code == 201, attempt.text
    changed = client.post(
        f"/api/v1/catalogue/{entry['entry_id']}/versions",
        headers=headers(key="revise"),
        json={
            **{k: v for k, v in formulation().items() if k != "kind"},
            "expected_current_object_version_id": entry["object_version_id"],
            "title": "Clarified statement",
        },
    ).json()
    pinned = client.get(
        "/api/v1/project-references",
        headers=headers(),
        params={"project_id": pin["project_id"]},
    ).json()["items"][0]
    assert pinned["object_version_id"] == entry["object_version_id"]
    assert pinned["latest_object_version_id"] == changed["object_version_id"]
    upgrade = client.post(
        f"/api/v1/project-references/{pin['id']}/versions",
        headers=headers(key="upgrade"),
        json={
            "expected_current_reference_version_id": pin["reference_version_id"],
            "object_version_id": changed["object_version_id"],
            "reason": "Read and accepted clarification",
        },
    )
    assert upgrade.status_code == 200, upgrade.text
    attempt_version_id = next(
        item["entity_id"]
        for item in attempt.json()["outputs"]
        if item["entity_type"] == "OBJECT_VERSION"
    )
    record = client.get(
        f"/api/v1/records/{attempt_version_id}",
        headers=headers(),
        params={"project_id": pin["project_id"]},
    ).json()
    assert [
        pin["target_object_version_id"]
        for pin in record["structural_relationships"]
        if pin["relationship_type"] == "ATTACHMENT"
    ] == [entry["object_version_id"]]


def test_work_privately_never_reuses_a_public_project(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    body = {"object_version_id": entry["object_version_id"]}
    public = client.post(
        "/api/v1/project-references", headers=headers(key="public-import"), json=body
    ).json()
    body["project_visibility"] = "PRIVATE"
    private = client.post(
        "/api/v1/project-references", headers=headers(key="private-import"), json=body
    ).json()
    assert private["project_id"] != public["project_id"]
    project_url = f"/api/v1/projects/{private['project_id']}"
    assert client.get(project_url, headers=headers()).json()["visibility"] == "PRIVATE"
    reused = client.post(
        "/api/v1/project-references", headers=headers(key="reuse-private"), json=body
    ).json()
    assert reused["project_id"] == private["project_id"]
    assert (
        client.patch(project_url, headers=headers(), json={"visibility": "PUBLIC"}).status_code
        == 200
    )
    new_private = client.post(
        "/api/v1/project-references", headers=headers(key="private-after-public"), json=body
    ).json()
    assert new_private["project_id"] not in (public["project_id"], private["project_id"])
    assert client.get(f"/api/v1/projects/{new_private['project_id']}").status_code == 404


@pytest.mark.parametrize("visibility", ["PUBLIC", "PRIVATE"])
def test_library_copy_is_independent_and_retry_safe(client: TestClient, visibility: str) -> None:
    enable(client)
    entry = admit(client)
    body = {
        "source_object_version_id": entry["object_version_id"],
        "project_visibility": visibility,
    }
    response = client.post("/api/v1/project-copies", headers=headers(key="copy"), json=body)
    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["object_id"] != entry["entry_id"]
    assert copy["object_version_id"] != entry["object_version_id"]
    assert copy["source_object_version_id"] == entry["object_version_id"]
    assert (
        client.post("/api/v1/project-copies", headers=headers(key="copy"), json=body).json() == copy
    )
    record = client.get(f"/api/v1/records/{copy['object_version_id']}", headers=headers()).json()
    assert record["content"]["content_md"] == formulation()["content_md"]
    assert record["content"]["assumptions_md"] == formulation()["assumptions_md"]
    assert [pin["target_object_version_id"] for pin in record["structural_relationships"]] == [
        entry["object_version_id"]
    ]
    pins = client.get(
        "/api/v1/project-references",
        headers=headers(),
        params={"project_id": copy["project_id"]},
    ).json()
    assert pins["items"] == []
    edited = client.post(
        f"/api/v1/objects/{copy['object_id']}/versions",
        headers=headers(key="edit-copy"),
        json={
            "expected_current_object_version_id": copy["object_version_id"],
            "snapshot": {
                "kind": record["kind"],
                "content": {
                    **record["content"],
                    "title": "My local formulation",
                    "content_md": "A revised project statement",
                },
                "structural_relationships": [],
                "change_summary": "Independent edit",
            },
        },
    )
    assert edited.status_code == 201, edited.text
    assert (
        client.get(f"/api/v1/records/{entry['object_version_id']}").json()["content"]["content_md"]
        == formulation()["content_md"]
    )
    existing = {
        "source_object_version_id": entry["object_version_id"],
        "project_id": copy["project_id"],
    }
    assert client.post("/api/v1/project-copies", json=existing).status_code == 401
    assert client.post(
        "/api/v1/project-copies", headers=headers("outsider", key="denied"), json=existing
    ).status_code in (403, 404)
    second = client.post(
        "/api/v1/project-copies", headers=headers(key="another-copy"), json=existing
    )
    assert second.status_code == 201, second.text
    assert second.json()["object_id"] != copy["object_id"]
    changed = client.post(
        f"/api/v1/catalogue/{entry['entry_id']}/versions",
        headers=headers(key="revise-source"),
        json={
            **{k: v for k, v in formulation().items() if k != "kind"},
            "expected_current_object_version_id": entry["object_version_id"],
            "content_md": "An updated Library statement",
        },
    )
    assert changed.status_code == 201, changed.text
    assert (
        client.get(f"/api/v1/records/{copy['object_version_id']}", headers=headers()).json()[
            "content"
        ]["content_md"]
        == formulation()["content_md"]
    )


def test_hidden_library_copy_rolls_back_new_project(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    with app.state.session_factory() as db:
        source = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert source is not None
        source.hidden = True
        db.commit()
        before = db.query(SqlProject).count()
    response = client.post(
        "/api/v1/project-copies",
        headers=headers(key="hidden-copy"),
        json={"source_object_version_id": entry["object_version_id"]},
    )
    assert response.status_code == 404, response.text
    with app.state.session_factory() as db:
        assert db.query(SqlProject).count() == before

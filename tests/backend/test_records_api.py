from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from test_catalogue_api import admit, enable, formulation, headers
from test_library_api import attempt_payload
from test_research_domain import create_object

from polycolab.db.models import SqlCatalogueEntry


def record_payload(
    revision_id: str,
    *,
    project_id: str | None = None,
    kind: str = "ATTEMPT",
    statement_revision_ids: list[str] | None = None,
    reported_outcome: str = "FAILED",
    explanation_md: str = "The step requires a stronger hypothesis",
) -> dict[str, Any]:
    payload = attempt_payload(revision_id, project_id)
    snapshot = payload["snapshot"]
    snapshot["kind"] = {"STATEMENT": "STATEMENT", "PROOF_SKETCH": "PROOF"}.get(kind, kind)
    snapshot["content"].update(reported_outcome=reported_outcome, explanation_md=explanation_md)
    snapshot["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": target}
        for target in ([revision_id] if statement_revision_ids is None else statement_revision_ids)
    ]
    if kind == "ATTEMPT":
        snapshot["structural_relationships"].append(
            {"relationship_type": "TARGET", "target_object_version_id": revision_id}
        )
    else:
        snapshot["content"].pop("outcome")
        snapshot["content"].pop("findings_md")
    return payload


def test_anonymous_catalogue_revision_history_is_paged_and_moderation_filtered(
    client: TestClient,
) -> None:
    app = enable(client)
    entry = admit(client)
    body = formulation()
    original_source = dict(body["source"])
    attempt = client.post(
        "/api/v1/objects",
        headers=headers(key="old-attempt"),
        json=attempt_payload(entry["object_version_id"]),
    ).json()
    attempt_id = next(
        item["entity_id"] for item in attempt["outputs"] if item["entity_type"] == "OBJECT_VERSION"
    )
    body.pop("kind")
    body["source"] = {**original_source, "version": "v3"}
    body.update(
        expected_current_object_version_id=entry["object_version_id"], title="Revised formulation"
    )
    revised = client.post(
        f"/api/v1/catalogue/{entry['entry_id']}/versions", headers=headers(key="revise"), json=body
    )
    assert revised.status_code == 201, revised.text
    exact = client.get(f"/api/v1/records/{entry['object_version_id']}").json()
    assert exact["catalogue"]["source"] == original_source
    assert exact["catalogue"]["entry_id"] == entry["entry_id"]
    assert exact["catalogue"]["source"]["version"] == "v2"
    old_research = client.get(
        "/api/v1/records", params={"statement_id": entry["object_version_id"]}
    ).json()
    assert [value["id"] for value in old_research["items"]] == [attempt_id]
    assert (
        client.get(
            "/api/v1/records", params={"statement_id": revised.json()["object_version_id"]}
        ).json()["items"]
        == []
    )
    page = client.get("/api/v1/records", params={"object_id": entry["entry_id"], "limit": 1}).json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    following = client.get(
        "/api/v1/records",
        params={"object_id": entry["entry_id"], "cursor": page["next_cursor"]},
    ).json()
    assert {item["id"] for item in page["items"] + following["items"]} == {
        entry["object_version_id"],
        revised.json()["object_version_id"],
    }
    with app.state.session_factory() as db:
        saved = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert saved is not None
        saved.hidden = True
        db.commit()
    assert (
        client.get("/api/v1/records", params={"object_id": entry["entry_id"]}).json()["items"] == []
    )


@pytest.mark.parametrize("kind", ["ATTEMPT", "STATEMENT"])
def test_full_snapshot_edits_preserve_explicit_metadata_and_exact_targets(
    client: TestClient, kind: str
) -> None:
    enable(client)
    entry = admit(client)
    project = client.post(
        "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    body = attempt_payload(entry["object_version_id"], project_id=project["id"])
    snapshot = body["snapshot"]
    snapshot["content"].update(
        assumptions_md="Finite connected graph",
        reported_outcome="FAILED",
        explanation_md="A stronger hypothesis is needed",
    )
    if kind == "STATEMENT":
        snapshot["kind"] = {"STATEMENT": "STATEMENT", "PROOF_SKETCH": "PROOF"}.get(kind, kind)
        snapshot["content"].pop("outcome")
        snapshot["content"].pop("findings_md")
        snapshot["structural_relationships"] = [
            pin
            for pin in snapshot["structural_relationships"]
            if pin["relationship_type"] == "ATTACHMENT"
        ]
    created = post_research(client, "/api/v1/objects", headers=headers(key="typed"), json=body)
    assert created.status_code == 201, created.text
    original = created.json()
    edit_payload = {
        "expected_current_object_version_id": original["current_object_version_id"],
        "snapshot": {
            **snapshot,
            "content": {
                **snapshot["content"],
                "title": "Clarified failure",
                "content_md": "The base case works but the induction step does not.",
            },
            "change_summary": "Clarify the argument",
        },
    }
    edited = post_research(
        client,
        f"/api/v1/objects/{original['id']}/versions",
        headers=headers(),
        json=edit_payload,
    )
    assert edited.status_code == 201, edited.text
    revised_id = edited.json()["current_object_version_id"]
    found = client.get(
        "/api/v1/discovery",
        headers=headers(),
        params={
            "scope": "member",
            "workspace_id": project["id"],
            "status": "FAILED",
            "kind": kind,
        },
    )
    assert [item["object_version"]["id"] for item in found.json()["items"]] == [revised_id]
    for revision_id in (original["current_object_version_id"], revised_id):
        response = client.get(
            f"/api/v1/records/{revision_id}",
            headers=headers(),
            params={"workspace_id": project["id"]},
        )
        assert response.status_code == 200, response.text
        value = response.json()
        for field in (
            "assumptions_md",
            "reported_outcome",
            "explanation_md",
        ):
            assert value["content"][field] == snapshot["content"][field]
        assert [
            (pin["relationship_type"], pin["target_object_version_id"])
            for pin in value["structural_relationships"]
        ] == [
            (pin["relationship_type"], pin["target_object_version_id"])
            for pin in original["current_object_version"]["structural_relationships"]
        ]
        assert client.get(f"/api/v1/records/{revision_id}").status_code == 404
    assert (
        post_research(
            client,
            f"/api/v1/objects/{original['id']}/versions",
            headers=headers(key="stale"),
            json=edit_payload,
        ).status_code
        == 409
    )


def test_older_editor_cannot_bypass_record_authorship(client: TestClient) -> None:
    enable(client)
    project = client.post(
        "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    other = client.get("/api/v1/users/me", headers=headers("contributor")).json()
    assert (
        client.post(
            f"/api/v1/workspaces/{project['id']}/members",
            headers=headers(),
            json={
                "user_id": other["id"],
                "role": "CONTRIBUTOR",
            },
        ).status_code
        == 201
    )
    created = create_object(
        client, project["id"], kind="NOTE", title="Private note", content="Original"
    )
    response = post_research(
        client,
        f"/api/v1/objects/{created['id']}/versions",
        headers=headers("contributor"),
        json={
            "expected_current_object_version_id": created["current_object_version_id"],
            "snapshot": {
                "kind": "NOTE",
                "content": {
                    **created["current_object_version"]["content"],
                    "title": "Changed",
                    "content_md": "Changed",
                },
                "structural_relationships": [],
            },
        },
    )
    assert response.status_code == 403


def test_records_scope_history_promotion_and_paging(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    payload = record_payload(entry["object_version_id"])
    response = post_research(client, "/api/v1/objects", headers=headers(), json=payload)
    assert response.status_code == 201, response.text
    first = response.json()
    assert post_research(client, "/api/v1/objects", headers=headers(), json=payload).json() == first
    public = client.get(f"/api/v1/records/{first['current_object_version_id']}")
    assert public.json()["content"]["reported_outcome"] == "FAILED"
    assert "The step requires a stronger hypothesis" in public.text
    for field in ("workspace_id", "session_id", "run_id"):
        assert field not in public.text
    assert public.json()["authorship"]["contribution_id"] is None
    payload["snapshot"]["content"]["title"] = "Reconsidered induction"
    edit = {
        "expected_current_object_version_id": first["current_object_version_id"],
        "snapshot": payload["snapshot"],
    }
    path = f"/api/v1/objects/{first['id']}/versions"
    assert client.post(path, headers=headers("outsider", "edit"), json=edit).status_code == 403
    revised = client.post(path, headers=headers(key="edit"), json=edit)
    assert revised.status_code == 201, revised.text
    assert client.post(path, headers=headers(key="stale"), json=edit).status_code == 409
    history = client.get("/api/v1/records", params={"object_id": first["id"], "limit": 1}).json()
    assert history["next_cursor"]
    assert client.get(
        "/api/v1/records",
        params={"object_id": first["id"], "cursor": history["next_cursor"]},
    ).json()["items"]
    supporting = record_payload(
        entry["object_version_id"], kind="STATEMENT", reported_outcome="UNASSESSED"
    )
    claim = post_research(
        client, "/api/v1/objects", headers=headers(key="claim"), json=supporting
    ).json()
    promotion = client.post(
        "/api/v1/catalogue/promotions",
        headers=headers(key="promote"),
        json={
            "object_version_id": claim["current_object_version_id"],
            "source": {"identifier": "paper", "version": "v1", "locator": "Lemma 2"},
            "reported_status": "Open",
            "reason": "Admit supporting claim",
        },
    )
    assert promotion.status_code == 201, promotion.text
    assert client.get(f"/api/v1/catalogue/{claim['id']}").status_code == 200
    with app.state.session_factory() as db:
        value = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert value is not None
        value.hidden = True
        db.commit()
    assert client.get(f"/api/v1/records/{first['current_object_version_id']}").status_code == 404


def test_private_public_relation_matrix(client: TestClient) -> None:
    enable(client)
    entry = admit(client)
    private_ids = []
    for key in ("one", "two"):
        project = client.post(
            "/api/v1/workspaces", headers=headers(), json={"visibility": "PRIVATE", "name": key}
        ).json()
        response = post_research(
            client,
            "/api/v1/objects",
            headers=headers(key=key),
            json=record_payload(
                entry["object_version_id"], project_id=project["id"], kind="STATEMENT"
            ),
        )
        assert response.status_code == 201, response.text
        private_ids.append((project["id"], response.json()["current_object_version_id"]))
    assert client.get(f"/api/v1/records/{private_ids[0][1]}").status_code == 404
    for index, (project, source, target, expected) in enumerate(
        (
            (private_ids[0][0], private_ids[0][1], entry["object_version_id"], 201),
            (private_ids[0][0], private_ids[0][1], private_ids[1][1], 404),
            (None, entry["object_version_id"], private_ids[0][1], 404),
            (None, entry["object_version_id"], entry["object_version_id"], 201),
        )
    ):
        response = client.post(
            "/api/v1/relations",
            headers=headers(key=f"rel-{index}"),
            json={
                "destination": {"kind": "workspace", "workspace_id": project}
                if project
                else {"kind": "library", "statement_object_version_id": source},
                "direction": "UNIDIRECTIONAL",
                "source_object_version_id": source,
                "target_object_version_id": target,
                "relationship_type": "USES",
                "description": "Research association",
            },
        )
        assert response.status_code == expected, response.text
    public = client.get(f"/api/v1/versions/{entry['object_version_id']}/relationships").json()
    assert len(public) == 1
    assert private_ids[0][1] not in str(public)


def test_unattached_public_statements_are_rejected_but_failure_explanation_is_optional(
    client: TestClient,
) -> None:
    enable(client)
    entry = admit(client)
    unattached = record_payload(entry["object_version_id"], statement_revision_ids=[])
    assert client.post("/api/v1/objects", headers=headers(), json=unattached).status_code == 422
    failed = record_payload(entry["object_version_id"], explanation_md="")
    assert client.post("/api/v1/objects", headers=headers(), json=failed).status_code == 201


def test_multiple_exact_targets_preserve_identity_and_moderation(client: TestClient) -> None:
    app = enable(client)
    first = admit(client)
    second = admit(client, key="second")
    response = post_research(
        client,
        "/api/v1/objects",
        headers=headers(key="multi"),
        json=record_payload(
            first["object_version_id"],
            kind="NOTE",
            statement_revision_ids=[first["object_version_id"], second["object_version_id"]],
        ),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    for target in (first, second):
        page = client.get(
            "/api/v1/records", params={"statement_id": target["object_version_id"]}
        ).json()
        assert [row["object_id"] for row in page["items"]] == [created["id"]]
    with app.state.session_factory() as db:
        entry = db.get(SqlCatalogueEntry, UUID(second["entry_id"]))
        assert entry is not None
        entry.hidden = True
        db.commit()
    hidden = client.get(f"/api/v1/records/{created['current_object_version_id']}")
    assert hidden.status_code == 404
    assert hidden.headers["cache-control"] == "private, no-store"
    assert (
        client.get("/api/v1/records", params={"statement_id": first["object_version_id"]}).json()[
            "items"
        ]
        == []
    )

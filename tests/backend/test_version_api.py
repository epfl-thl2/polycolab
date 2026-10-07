"""Wire-level checks for the object-version API cutover."""

import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, formulation
from test_research_domain import create_workspace, headers


@pytest.mark.parametrize(
    "document",
    ["skills/polycolab/SKILL.md", "docs-site/docs/developers/agent-runs.md"],
)
def test_documented_object_creation_example(client: TestClient, document: str) -> None:
    enable(client)
    project = create_workspace(client)
    source = (Path(__file__).resolve().parents[2] / document).read_text()
    example = source.split("```json\n", 1)[1].split("```", 1)[0]
    body = json.loads(example)
    body["destination"]["workspace_id"] = str(project)
    request_headers = headers("owner")
    response = client.post("/api/v1/objects", headers=request_headers, json=body)
    assert response.status_code == 201, response.text
    version_id = next(
        output["entity_id"]
        for output in response.json()["outputs"]
        if output["entity_type"] == "OBJECT_VERSION"
    )
    exact = client.get(f"/api/v1/versions/{version_id}", headers=headers("owner"))
    assert exact.status_code == 200, exact.text
    assert exact.json()["content"] == body["snapshot"]["content"]
    assert exact.json()["structural_relationships"] == []
    replay = client.post("/api/v1/objects", headers=request_headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["outputs"] == response.json()["outputs"]


def snapshot() -> dict[str, Any]:
    return {
        "kind": "STATEMENT",
        "content": {
            "statement_label": "CLAIM",
            "title": "Claim",
            "content_md": "Full content",
            "assumptions_md": "None",
            "reported_outcome": None,
            "explanation_md": None,
        },
        "structural_relationships": [],
        "change_summary": None,
    }


def test_legacy_scoped_relationship_write_is_not_registered(client: TestClient) -> None:
    assert "post" not in cast(FastAPI, client.app).openapi()["paths"]["/api/v1/records"]
    assert "/api/v1/scoped-relations" not in cast(FastAPI, client.app).openapi()["paths"]
    assert (
        client.post("/api/v1/scoped-relations", headers=headers("owner"), json={}).status_code
        == 404
    )


def test_correction_creation_keeps_catalogue_metadata_outside_version_content(
    client: TestClient,
) -> None:
    enable(client)
    statement = admit(client)
    target = statement["object_version_id"]
    proposed = formulation()
    proposed.pop("kind")
    proposed["expected_current_object_version_id"] = target
    value = snapshot()
    value["kind"] = "NOTE"
    value["content"].pop("statement_label", None)
    value["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": target}
    ]
    body = {
        "destination": {"kind": "library", "statement_object_version_id": target},
        "snapshot": value,
        "catalogue_suggestion": proposed,
    }
    retry_headers = headers("owner")
    response = client.post("/api/v1/objects", headers=retry_headers, json=body)
    assert response.status_code == 201, response.text
    repeated = client.post("/api/v1/objects", headers=retry_headers, json=body)
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["outputs"] == response.json()["outputs"]
    assert repeated.json()["contribution_id"] == response.json()["contribution_id"]
    assert repeated.json()["replayed"] is True
    version_id = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    exact = client.get(f"/api/v1/versions/{version_id}")
    assert exact.status_code == 200, exact.text
    version = exact.json()
    assert version["catalogue"]["suggestion"]["expected_current_object_version_id"] == target
    assert "catalogue_suggestion" not in version["content"]
    assert "suggestion" not in version["content"]
    value["kind"] = "STATEMENT"
    rejected = client.post("/api/v1/objects", headers=headers("owner"), json=body)
    assert rejected.status_code == 422, rejected.text


def test_attempt_history_returns_complete_exact_version_snapshots(client: TestClient) -> None:
    project = create_workspace(client)
    target = create_versioned(client, project, snapshot())
    value = snapshot()
    value["kind"] = "ATTEMPT"
    value["content"].pop("statement_label", None)
    value["content"].update(outcome="PARTIAL", findings_md="A useful bound")
    value["structural_relationships"] = [
        {"relationship_type": "TARGET", "target_object_version_id": target["id"]},
        {
            "relationship_type": "EVIDENCE",
            "target_object_version_id": target["id"],
            "position": 7,
            "evidence_role": "INPUT",
        },
    ]
    attempt = create_versioned(client, project, value)
    path = f"/api/v1/research/objects/{target['object_id']}/attempts"
    params = {"workspace_id": project, "scope": "member", "target_object_version_id": target["id"]}
    response = client.get(path, headers=headers("owner"), params=params)
    assert response.status_code == 200, response.text
    assert response.json() == {"items": [attempt], "next_cursor": None}
    assert client.get(path, headers=headers("outsider"), params=params).status_code == 404
    assert client.get(path).status_code == 404
    unrelated = create_versioned(client, project, snapshot())
    assert (
        client.get(
            path,
            headers=headers("owner"),
            params={**params, "target_object_version_id": unrelated["id"]},
        ).status_code
        == 404
    )


def create_versioned(client: TestClient, project: str, value: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/v1/objects",
        headers=headers("owner"),
        json={"destination": {"kind": "workspace", "workspace_id": project}, "snapshot": value},
    )
    assert response.status_code == 201, response.text
    version_id = next(
        r["entity_id"] for r in response.json()["outputs"] if r["entity_type"] == "OBJECT_VERSION"
    )
    response = client.get(f"/api/v1/versions/{version_id}", headers=headers("owner"))
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_public_attempt_history_matches_the_public_exact_projection(client: TestClient) -> None:
    project = create_workspace(client, visibility="PUBLIC")
    target = create_versioned(client, project, snapshot())
    value = snapshot()
    value["kind"] = "ATTEMPT"
    value["content"].pop("statement_label", None)
    value["content"].update(outcome="PARTIAL", findings_md="Public finding")
    value["structural_relationships"] = [
        {"relationship_type": "TARGET", "target_object_version_id": target["id"]}
    ]
    attempt = create_versioned(client, project, value)
    exact = client.get(f"/api/v1/versions/{attempt['id']}")
    assert exact.status_code == 200, exact.text
    history = client.get(
        f"/api/v1/research/objects/{target['object_id']}/attempts",
        params={"target_object_version_id": target["id"]},
    )
    assert history.status_code == 200, history.text
    assert history.json()["items"] == [exact.json()]
    assert exact.json()["authorship"]["contribution_id"] is None
    assert exact.json()["structural_relationships"][0]["ownership_scope_id"] is None


def test_public_search_uses_the_latest_released_version_not_a_private_head(
    client: TestClient,
) -> None:
    from polycolab.catalogue.admission import _release
    from polycolab.db.models import (
        SqlContributionEnvelope,
        SqlObjectRevision,
        SqlPublicResearchAnchor,
        SqlResearchObject,
    )

    app = cast(FastAPI, client.app)
    enable(client)
    statement = admit(client)
    project = create_workspace(client)
    value = snapshot()
    value["content"]["title"] = "Public formulation"
    value["structural_relationships"] = [
        {
            "relationship_type": "ATTACHMENT",
            "target_object_version_id": statement["object_version_id"],
        }
    ]
    first = create_versioned(client, project, value)
    with app.state.session_factory() as session:
        obj = session.get(SqlResearchObject, UUID(first["object_id"]))
        version = session.get(SqlObjectRevision, UUID(first["id"]))
        assert obj is not None and version is not None
        contribution = session.get(SqlContributionEnvelope, obj.contribution_id)
        assert contribution is not None
        _release(session, obj, version, contribution)
        session.add(
            SqlPublicResearchAnchor(revision_id=version.id, entry_id=UUID(statement["entry_id"]))
        )
        session.commit()
    assert client.get(f"/api/v1/versions/{first['id']}").status_code == 200
    value["content"]["title"] = "Confidential new formulation"
    updated = client.post(
        f"/api/v1/objects/{first['object_id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": first["id"],
            "snapshot": value,
        },
    )
    assert updated.status_code == 201, updated.text
    attempts_path = f"/api/v1/research/objects/{first['object_id']}/attempts"
    public_history = client.get(attempts_path)
    assert public_history.status_code == 200, public_history.text
    assert public_history.json() == {"items": [], "next_cursor": None}
    private_head = next(
        item["entity_id"]
        for item in updated.json()["outputs"]
        if item["entity_type"] == "OBJECT_VERSION"
    )
    assert (
        client.get(attempts_path, params={"target_object_version_id": private_head}).status_code
        == 404
    )
    public = client.get("/api/v1/search", params={"q": "Public formulation"})
    assert public.status_code == 200, public.text
    assert len(public.json()["items"]) == 1
    selected = public.json()["items"][0]
    assert selected["current_object_version_id"] == first["id"]
    assert selected["current_object_version"]["content"]["title"] == "Public formulation"
    assert client.get("/api/v1/search", params={"q": "Confidential"}).json()["items"] == []
    private = client.get(
        "/api/v1/search", headers=headers("owner"), params={"q": "Confidential", "scope": "member"}
    )
    assert private.status_code == 200, private.text
    assert private.json()["items"][0]["current_object_version_id"] != first["id"]


def test_bounded_version_displays_use_explicit_ids_and_enforce_access(client: TestClient) -> None:
    project = create_workspace(client)
    first = create_versioned(client, project, snapshot())
    second = create_versioned(client, project, snapshot())
    path = "/api/v1/research/versions/display"
    body = {"workspace_id": project, "object_version_ids": [second["id"], first["id"]]}
    response = client.post(path, headers=headers("owner"), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {
            "object_version_id": version["id"],
            "object_id": version["object_id"],
            "kind": "STATEMENT",
            "title": "Claim",
        }
        for version in (second, first)
    ]
    assert client.post(path, headers=headers("outsider"), json=body).status_code == 404
    assert (
        client.post(
            path,
            headers=headers("owner"),
            json={"workspace_id": project, "revision_ids": [first["id"]]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers=headers("owner"),
            json={"workspace_id": project, "object_version_ids": [first["id"], first["id"]]},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/research/revisions/display", headers=headers("owner"), json=body
        ).status_code
        == 404
    )


def test_dependents_are_directed_and_pinned_to_the_selected_object_version(
    client: TestClient,
) -> None:
    project = create_workspace(client)
    source = create_versioned(client, project, snapshot())
    target = create_versioned(client, project, snapshot())
    destination = {"kind": "workspace", "workspace_id": project}
    for declaration in (
        {
            "direction": "UNIDIRECTIONAL",
            "relationship_type": "USES",
            "source_object_version_id": source["id"],
            "target_object_version_id": target["id"],
        },
        {
            "direction": "BIDIRECTIONAL",
            "relationship_type": "EQUIVALENT_TO",
            "first_object_version_id": source["id"],
            "second_object_version_id": target["id"],
        },
    ):
        response = client.post(
            "/api/v1/relations",
            headers=headers("owner"),
            json={
                "destination": destination,
                **declaration,
            },
        )
        assert response.status_code == 201, response.text
    path = f"/api/v1/objects/{target['object_id']}/dependents"
    initial = client.get(path, headers=headers("owner"), params={"object_version_id": target["id"]})
    assert initial.status_code == 200, initial.text
    assert len(initial.json()) == 1
    edge = initial.json()[0]
    assert edge["direction"] == "UNIDIRECTIONAL"
    assert edge["source_object_version_id"] == source["id"]
    assert edge["target_object_version_id"] == target["id"]
    assert "source_revision_id" not in edge
    source_dependents = client.get(
        f"/api/v1/objects/{source['object_id']}/dependents",
        headers=headers("owner"),
        params={"object_version_id": source["id"]},
    )
    assert source_dependents.status_code == 200, source_dependents.text
    assert source_dependents.json() == []
    assert (
        client.get(
            path, headers=headers("owner"), params={"object_version_id": source["id"]}
        ).status_code
        == 404
    )
    updated = client.post(
        f"/api/v1/objects/{target['object_id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": target["id"],
            "snapshot": snapshot(),
        },
    )
    assert updated.status_code == 201, updated.text
    assert client.get(path, headers=headers("owner")).json() == []
    assert client.get(
        path, headers=headers("owner"), params={"object_version_id": target["id"]}
    ).json() == [edge]
    assert (
        client.get(
            path, headers=headers("outsider"), params={"object_version_id": target["id"]}
        ).status_code
        == 404
    )


def test_exact_and_history_share_the_complete_version_contract(client: TestClient) -> None:
    project = create_workspace(client)
    claim = create_versioned(client, project, snapshot())
    proof = snapshot()
    proof["kind"] = "PROOF"
    proof["content"].pop("statement_label", None)
    proof["content"]["reported_progress"] = "POTENTIAL"
    proof["structural_relationships"] = [
        {"relationship_type": role, "target_object_version_id": claim["id"]}
        for role in ("ATTACHMENT", "CONCLUSION")
    ]
    obj = create_versioned(client, project, proof)
    version_id = obj["id"]
    exact = client.get(f"/api/v1/versions/{version_id}", headers=headers("owner"))
    assert exact.status_code == 200, exact.text
    version = exact.json()
    assert version["id"] == version_id
    assert version["kind"] == "PROOF"
    assert version["content"]["reported_progress"] == "POTENTIAL"
    assert version["previous_object_version_id"] is None
    assert len(version["structural_relationships"]) == 2
    for relationship in version["structural_relationships"]:
        assert relationship["id"]
        assert relationship["direction"] == "UNIDIRECTIONAL"
        assert relationship["binding"] == "STRUCTURAL"
        assert relationship["source_object_version_id"] == version_id
        assert relationship["authorship"] == version["authorship"]
    history = client.get(f"/api/v1/objects/{obj['object_id']}/versions", headers=headers("owner"))
    assert history.status_code == 200, history.text
    assert history.json()["items"] == [version]
    embedded = client.get(f"/api/v1/objects/{version['object_id']}", headers=headers("owner"))
    assert embedded.status_code == 200, embedded.text
    assert embedded.json()["current_object_version"] == version
    assert embedded.json()["current_object_version_id"] == version_id
    assert "current_revision_id" not in embedded.json()
    scoped = client.get(
        f"/api/v1/records/{version_id}", headers=headers("owner"), params={"workspace_id": project}
    )
    assert scoped.status_code == 200, scoped.text
    assert scoped.json() == version
    listing = client.get(
        "/api/v1/records",
        headers=headers("owner"),
        params={"workspace_id": project, "scope": "member", "object_id": version["object_id"]},
    )
    assert listing.status_code == 200, listing.text
    assert listing.json()["items"] == [version]
    discovery = client.get(
        "/api/v1/discovery",
        headers=headers("owner"),
        params={"workspace_id": project, "scope": "member"},
    )
    assert discovery.status_code == 200, discovery.text
    assert (
        next(
            hit["object_version"]
            for hit in discovery.json()["items"]
            if hit["object_version"]["id"] == version_id
        )
        == version
    )
    assert (
        client.get(f"/api/v1/revisions/{version_id}", headers=headers("owner")).status_code == 404
    )
    assert client.get(f"/api/v1/versions/{version_id}").status_code == 404
    assert (
        client.get(f"/api/v1/versions/{version_id}", headers=headers("outsider")).status_code == 404
    )


def test_public_versions_do_not_expose_private_scope_metadata(client: TestClient) -> None:
    project = create_workspace(client, visibility="PUBLIC")
    obj = create_versioned(client, project, snapshot())
    version_id = obj["id"]
    public = client.get(f"/api/v1/versions/{version_id}")
    assert public.status_code == 200, public.text
    version = public.json()
    assert version["authorship"]["contribution_id"] is None
    history = client.get(f"/api/v1/objects/{obj['object_id']}/versions")
    assert history.status_code == 200, history.text
    assert history.json()["items"] == [version]
    embedded = client.get(f"/api/v1/objects/{version['object_id']}")
    assert embedded.status_code == 200, embedded.text
    assert embedded.json()["current_object_version"] == version
    assert "ownership_scope_id" not in embedded.json()


def test_full_snapshot_update_removes_pins_and_is_idempotent(client: TestClient) -> None:
    project = create_workspace(client)
    target = create_versioned(client, project, snapshot())
    initial = snapshot()
    initial["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": target["id"]}
    ]
    first = create_versioned(client, project, initial)
    path = f"/api/v1/objects/{first['object_id']}/versions"
    value = snapshot()
    value["content"]["assumptions_md"] = "Updated assumptions"
    body = {"expected_current_object_version_id": first["id"], "snapshot": value}
    retry_headers = headers("owner")
    response = client.post(path, headers=retry_headers, json=body)
    assert response.status_code == 201, response.text
    replay = client.post(path, headers=retry_headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["replayed"]
    assert replay.json()["outputs"] == response.json()["outputs"]
    stale = client.post(path, headers=headers("owner"), json=body)
    assert stale.status_code == 409, stale.text
    history = client.get(path, headers=headers("owner")).json()["items"]
    assert len(history) == 2
    assert history[0]["number"] == 2
    assert history[0]["previous_object_version_id"] == first["id"]
    assert history[0]["content"]["assumptions_md"] == "Updated assumptions"
    assert history[0]["content"]["reported_outcome"] is None
    assert history[0]["change_summary"] is None
    assert history[0]["structural_relationships"] == []
    assert history[1] == first


def test_proof_positions_are_not_renumbered_on_write(client: TestClient) -> None:
    project = create_workspace(client)
    conclusion = create_versioned(client, project, snapshot())
    premise = create_versioned(client, project, snapshot())
    proof = snapshot()
    proof["kind"] = "PROOF"
    proof["content"].pop("statement_label", None)
    proof["content"]["reported_progress"] = "PARTIAL"
    proof["structural_relationships"] = [
        {"relationship_type": "ATTACHMENT", "target_object_version_id": v["id"]}
        for v in (conclusion, premise)
    ] + [
        {"relationship_type": "CONCLUSION", "target_object_version_id": conclusion["id"]},
        {"relationship_type": "PREMISE", "target_object_version_id": premise["id"], "position": 7},
    ]
    saved = create_versioned(client, project, proof)
    assert (
        next(r for r in saved["structural_relationships"] if r["relationship_type"] == "PREMISE")[
            "position"
        ]
        == 7
    )


def test_comments_use_explicit_object_version_references(client: TestClient) -> None:
    project = create_workspace(client)
    version = create_versioned(client, project, snapshot())
    path = f"/api/v1/objects/{version['object_id']}/comments"
    old = client.post(
        path, headers=headers("owner"), json={"revision_id": version["id"], "body_md": "Old wire"}
    )
    assert old.status_code == 422
    created = client.post(
        path,
        headers=headers("owner"),
        json={"object_version_id": version["id"], "body_md": "Exact version"},
    )
    assert created.status_code == 201, created.text
    read = client.get(path, headers=headers("owner"))
    assert read.status_code == 200, read.text
    assert read.json()["items"][0]["object_version_id"] == version["id"]
    assert "revision_id" not in read.json()["items"][0]


def test_relationship_responses_have_symmetric_endpoints(client: TestClient) -> None:
    project = create_workspace(client)
    first = create_versioned(client, project, snapshot())
    second = create_versioned(client, project, snapshot())
    response = client.post(
        "/api/v1/relations",
        headers=headers("owner"),
        json={
            "direction": "BIDIRECTIONAL",
            "relationship_type": "EQUIVALENT_TO",
            "destination": {"kind": "workspace", "workspace_id": project},
            "first_object_version_id": second["id"],
            "second_object_version_id": first["id"],
        },
    )
    assert response.status_code == 201, response.text
    relation_id = response.json()["outputs"][0]["entity_id"]
    for version in (first, second):
        page = client.get(
            f"/api/v1/objects/{version['object_id']}/relations", headers=headers("owner")
        )
        assert page.status_code == 200, page.text
        relation = page.json()["items"][0]
        assert relation["id"] == relation_id
        assert relation["direction"] == "BIDIRECTIONAL"
        assert [
            relation["first_object_version_id"],
            relation["second_object_version_id"],
        ] == sorted([first["id"], second["id"]])
        assert "source_object_version_id" not in relation
        assert "source_revision_id" not in relation
        assert relation["description"] is None
        scoped = client.get(
            f"/api/v1/versions/{version['id']}/relationships",
            headers=headers("owner"),
            params={"workspace_id": project},
        )
        assert scoped.status_code == 200, scoped.text
        assert scoped.json() == [relation]
        graph = client.get(
            f"/api/v1/objects/{version['object_id']}/neighborhood",
            headers=headers("owner"),
            params={"object_version_id": version["id"]},
        )
        assert graph.status_code == 200, graph.text
        assert graph.json()["object_version_id"] == version["id"]
        assert graph.json()["relationships"] == [relation]
        assert {node["object_version_id"] for node in graph.json()["nodes"]} == {
            first["id"],
            second["id"],
        }

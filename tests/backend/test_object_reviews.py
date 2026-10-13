"""Review outcomes are attributable, version-pinned, and independent of truth."""

from typing import Any

from fastapi.testclient import TestClient
from test_research_domain import create_project, headers


def create_statement(client: TestClient, project: str, *, label: str = "CONJECTURE") -> str:
    response = client.post(
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "destination": {"kind": "project", "project_id": str(project)},
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    "title": "A conjecture",
                    "content_md": "Every example has property P.",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                    "statement_label": label,
                },
                "structural_relationships": [],
                "change_summary": None,
            },
        },
    )
    assert response.status_code == 201, response.text
    return next(
        str(item["entity_id"])
        for item in response.json()["outputs"]
        if item["entity_type"] == "OBJECT_VERSION"
    )


def test_canonical_statement_and_review_history(client: TestClient) -> None:
    project = create_project(client)
    version = create_statement(client, project)
    exact = client.get(f"/api/v1/versions/{version}", headers=headers("owner")).json()
    assert exact["kind"] == "STATEMENT"
    assert exact["content"]["statement_label"] == "CONJECTURE"
    body = {
        "object_version_id": version,
        "outcome": "ISSUES_FOUND",
        "scope": "Quantifiers",
        "rationale": "The empty case needs attention.",
        "evidence_object_version_ids": [],
    }
    request_headers = headers("owner")
    first = client.post("/api/v1/reviews", headers=request_headers, json=body)
    assert first.status_code == 201, first.text
    replay = client.post("/api/v1/reviews", headers=request_headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["replayed"]
    current = client.get(f"/api/v1/reviews/{version}?current=true", headers=headers("owner"))
    assert current.status_code == 200, current.text
    assert len(current.json()["items"]) == 1
    assert current.json()["items"][0]["self_review"]
    summary = client.post(
        "/api/v1/reviews/summary",
        headers=headers("owner"),
        params={"project_id": str(project)},
        json={"object_version_ids": [version]},
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()[0]["human"]["issues_found"] == 1
    assert summary.json()[0]["formal"] == "UNAVAILABLE"
    withdrawn = client.post(
        "/api/v1/reviews",
        headers=headers("owner"),
        json={**body, "outcome": None, "withdrawn": True},
    )
    assert withdrawn.status_code == 201, withdrawn.text
    current = client.get(f"/api/v1/reviews/{version}?current=true", headers=headers("owner")).json()
    assert len(current["items"]) == 1
    assert current["items"][0]["withdrawn"]
    history = client.get(f"/api/v1/reviews/{version}", headers=headers("owner")).json()
    assert len(history["items"]) == 2


def test_review_rejects_spoofed_actor_and_wrong_outcome(client: TestClient) -> None:
    project = create_project(client)
    version = create_statement(client, project)
    body = {
        "object_version_id": version,
        "outcome": "SUPPORTS",
        "scope": "Argument",
        "rationale": "Reviewed",
    }
    extras: list[dict[str, Any]] = [
        {"actor_kind": "AGENT"},
        {"withdrawn": True},
        {"outcome": "VERIFIED"},
        {"scope": " "},
    ]
    for extra in extras:
        response = client.post("/api/v1/reviews", headers=headers("owner"), json={**body, **extra})
        assert response.status_code == 422, response.text


def test_old_kind_writes_are_rejected(client: TestClient) -> None:
    project = create_project(client)
    for kind in ("CLAIM", "PROOF_SKETCH", "IDEA", "DISCUSSION", "COUNTEREXAMPLE", "COMPUTATION"):
        response = client.post(
            "/api/v1/objects",
            headers=headers("owner"),
            json={
                "destination": {"kind": "project", "project_id": str(project)},
                "snapshot": {
                    "kind": kind,
                    "content": {
                        "title": "Old",
                        "content_md": "Old",
                        "assumptions_md": "None",
                        "reported_outcome": None,
                        "explanation_md": None,
                    },
                    "structural_relationships": [],
                },
            },
        )
        assert response.status_code == 422, response.text


def test_reviews_are_private_version_pinned_and_conflicts_remain_visible(
    client: TestClient,
) -> None:
    from test_research_domain import add_member

    project = create_project(client)
    add_member(client, project, "contributor", "CONTRIBUTOR")
    version = create_statement(client, project)
    body = {
        "object_version_id": version,
        "outcome": "SUPPORTS",
        "scope": "Argument",
        "rationale": "Reviewed",
    }
    assert client.post("/api/v1/reviews", headers=headers("owner"), json=body).status_code == 201
    assert (
        client.post(
            "/api/v1/reviews",
            headers=headers("contributor"),
            json={**body, "outcome": "ISSUES_FOUND"},
        ).status_code
        == 201
    )
    assert client.get(f"/api/v1/reviews/{version}").status_code == 404
    assert client.get(f"/api/v1/reviews/{version}", headers=headers("outsider")).status_code == 404
    summary = client.post(
        "/api/v1/reviews/summary",
        headers=headers("owner"),
        params={"project_id": project},
        json={"object_version_ids": [version]},
    ).json()[0]
    assert summary["human"] == {
        "reviewed": 0,
        "supports": 1,
        "issues_found": 1,
        "inconclusive": 0,
        "self_reviews": 1,
    }
    exact = client.get(f"/api/v1/versions/{version}", headers=headers("owner")).json()
    response = client.post(
        f"/api/v1/objects/{exact['object_id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": version,
            "snapshot": {
                "kind": "STATEMENT",
                "content": {**exact["content"], "title": "New version"},
                "structural_relationships": [],
            },
        },
    )
    assert response.status_code == 201, response.text
    new_version = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    assert (
        client.get(f"/api/v1/reviews/{new_version}", headers=headers("owner")).json()["items"] == []
    )


def test_external_reviews_require_opt_in_and_have_server_identity(client: TestClient) -> None:
    project = create_project(client)
    version = create_statement(client, project)
    agent = client.post(
        "/api/v1/account/agents", headers=headers("owner"), json={"name": "Review agent"}
    ).json()
    body = {
        "object_version_id": version,
        "outcome": "INCONCLUSIVE",
        "scope": "Argument",
        "rationale": "Needs a stronger premise",
    }
    for allowed in (False, True):
        key = client.post(
            "/api/v1/account/agent-keys",
            headers=headers("owner"),
            json={"name": "Review key", "agent_id": agent["id"], "allow_reviews": allowed},
        )
        assert key.status_code == 201, key.text
        response = client.post("/api/v1/reviews", headers=headers(key.json()["secret"]), json=body)
        assert response.status_code == (201 if allowed else 403), response.text
    review = client.get(f"/api/v1/reviews/{version}", headers=headers("owner")).json()["items"][0]
    assert review["actor_kind"] == "AGENT"
    assert review["reviewer_name"] == "Review agent"
    assert not review["self_review"]
    assert review["model_id"] is None


def test_publication_explicitly_selects_reviews_and_closes_evidence(client: TestClient) -> None:
    from test_catalogue_api import enable

    enable(client)
    project = create_project(client)
    version = create_statement(client, project)
    evidence = create_statement(client, project, label="LEMMA")
    response = client.post(
        "/api/v1/reviews",
        headers=headers("owner"),
        json={
            "object_version_id": version,
            "outcome": "SUPPORTS",
            "scope": "Argument",
            "rationale": "Uses the lemma",
            "evidence_object_version_ids": [evidence],
        },
    )
    assert response.status_code == 201, response.text
    review_id = response.json()["outputs"][0]["entity_id"]
    selection = {"project_id": project, "object_version_ids": [version]}
    preview = client.post("/api/v1/publication/preview", headers=headers("owner"), json=selection)
    assert preview.status_code == 200, preview.text
    published = client.post(
        "/api/v1/publication/confirm",
        headers=headers("owner"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Share statement only",
        },
    )
    assert published.status_code == 201, published.text
    assert client.get(f"/api/v1/reviews/{version}").json()["items"] == []
    selection["review_ids"] = [review_id]
    preview = client.post("/api/v1/publication/preview", headers=headers("owner"), json=selection)
    assert preview.status_code == 200, preview.text
    assert evidence in preview.json()["required_object_version_ids"]
    published = client.post(
        "/api/v1/publication/confirm",
        headers=headers("owner"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Share review and evidence",
        },
    )
    assert published.status_code == 201, published.text
    assert client.get(f"/api/v1/reviews/{version}").json()["items"][0]["id"] == review_id


def test_review_acknowledgement_has_optional_comment(client: TestClient) -> None:
    project = create_project(client)
    version = create_statement(client, project)
    body = {"object_version_id": version, "outcome": "REVIEWED"}
    response = client.post("/api/v1/reviews", headers=headers("owner"), json=body)
    assert response.status_code == 201, response.text
    current = client.get(f"/api/v1/reviews/{version}?current=true", headers=headers("owner")).json()
    review = current["items"][0]
    assert review["rationale"] == ""
    assert review["reviewer_name"]
    assert review["is_mine"]
    assert review["actor_kind"] == "HUMAN"
    summary = client.post(
        "/api/v1/reviews/summary",
        headers=headers("owner"),
        params={"project_id": project},
        json={"object_version_ids": [version]},
    ).json()[0]
    assert summary["human"]["reviewed"] == 1
    assert summary["human"]["supports"] == 0
    removed = client.post(
        "/api/v1/reviews",
        headers=headers("owner"),
        json={**body, "outcome": None, "withdrawn": True},
    )
    assert removed.status_code == 201, removed.text

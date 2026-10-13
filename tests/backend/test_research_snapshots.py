"""Complete research snapshots survive session closure and batch their child reads."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from test_research_domain import create_object, create_project, headers

from polycolab.db.models import SqlRecordModeration, SqlRecordRevision, SqlResearchObject, SqlUser
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.entities.enums import ResearchObjectKind
from polycolab.entities.research import ProofSketchVersion, StatementVersion
from polycolab.research.snapshots import ResearchSnapshots


@contextmanager
def queries(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_snapshots_batch_children_and_work_after_session_close(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    project_id = create_project(client)
    statement = create_object(client, project_id)
    proof = create_object(client, project_id, kind="PROOF_SKETCH")
    statement_id = UUID(statement["current_object_version_id"])
    proof_id = UUID(proof["current_object_version_id"])
    with app.state.session_factory() as session:
        with queries(app.state.engine) as single_queries:
            SqlResearchReadStore(session).versions([proof_id])
    with app.state.session_factory() as session:
        with queries(app.state.engine) as batch_queries:
            snapshots = SqlResearchReadStore(session).versions([statement_id, proof_id])
    assert len(single_queries) == len(batch_queries)
    assert isinstance(snapshots[statement_id], StatementVersion)
    proof_snapshot = snapshots[proof_id]
    assert isinstance(proof_snapshot, ProofSketchVersion)
    assert (
        proof_snapshot.conclusion_object_version_id in proof_snapshot.statement_object_version_ids
    )
    assert len(proof_snapshot.structural_relationships) == 2
    assert proof_snapshot.content.title == proof["current_object_version"]["content"]["title"]
    assert snapshots[statement_id].content.content_md == "x"
    with app.state.session_factory() as session:
        objects = ResearchSnapshots(SqlResearchReadStore(session)).selected_objects([proof_id])
    assert objects[0].object.current_object_version_id == proof_id
    assert objects[0].version == proof_snapshot


def test_history_is_complete_batched_and_preserves_previous_content(client: TestClient) -> None:
    project_id = create_project(client)
    proof = create_object(client, project_id, kind="PROOF_SKETCH")
    first_id = proof["current_object_version_id"]
    original = proof["current_object_version"]
    created = client.post(
        f"/api/v1/objects/{proof['id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": first_id,
            "snapshot": {
                "kind": "PROOF",
                "content": {
                    **original["content"],
                    "title": "A new approach",
                    "content_md": "New body",
                    "reported_progress": "PARTIAL",
                },
                "change_summary": "Clarify the proof",
                "structural_relationships": [
                    {
                        "relationship_type": pin["relationship_type"],
                        "target_object_version_id": pin["target_object_version_id"],
                    }
                    for pin in original["structural_relationships"]
                ],
            },
        },
    )
    assert created.status_code == 201, created.text
    app = cast(FastAPI, client.app)
    path = f"/api/v1/objects/{proof['id']}/versions"
    with queries(app.state.engine) as one_queries:
        one = client.get(path, headers=headers("owner"), params={"limit": 1}).json()
    with queries(app.state.engine) as two_queries:
        two = client.get(path, headers=headers("owner"), params={"limit": 2}).json()
    assert len(one_queries) == len(two_queries)
    assert one["next_cursor"]
    assert two["next_cursor"] is None
    assert two["items"][1] == original
    assert two["items"][0]["previous_object_version_id"] == first_id
    assert two["items"][0]["content"]["reported_progress"] == "PARTIAL"
    second_page = client.get(
        path, headers=headers("owner"), params={"limit": 1, "cursor": one["next_cursor"]}
    ).json()
    assert second_page["items"] == [original]
    exact = client.get(f"/api/v1/versions/{first_id}", headers=headers("owner")).json()
    assert exact == original


@pytest.mark.parametrize("kind", [ResearchObjectKind.PROOF, ResearchObjectKind.ATTEMPT])
def test_pre_structure_rows_remain_readable(client: TestClient, kind: ResearchObjectKind) -> None:
    project_id = create_project(client)
    obj = create_object(client, project_id, kind="NOTE")
    app = cast(FastAPI, client.app)
    # The SQLite fixture represents a PROOF persisted before migration 0012;
    # current production mutations cannot change object kind or omit structure.
    with app.state.session_factory() as session:
        row = session.get(SqlResearchObject, UUID(obj["id"]))
        typed = session.get(SqlRecordRevision, UUID(obj["current_object_version_id"]))
        assert row is not None and typed is not None
        row.kind = kind
        typed.kind = kind.value
        session.commit()
    response = client.get(
        f"/api/v1/versions/{obj['current_object_version_id']}", headers=headers("owner")
    )
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == kind.value
    if kind is ResearchObjectKind.PROOF:
        assert response.json()["content"]["reported_progress"] is None
    else:
        assert response.json()["legacy_unstructured"] is True
        assert response.json()["content"]["outcome"] is None
    assert response.json()["structural_relationships"] == []


def test_legacy_statement_release_retains_frozen_author(client: TestClient) -> None:
    from test_catalogue_api import admit, enable

    app = enable(client)
    entry = admit(client)
    original = client.get(f"/api/v1/versions/{entry['object_version_id']}").json()
    user_id = client.get("/api/v1/users/me", headers=headers("owner")).json()["id"]
    with app.state.session_factory() as session:
        user = session.get(SqlUser, UUID(user_id))
        assert user is not None
        user.display_name = "Changed after release"
        session.commit()
    exact = client.get(f"/api/v1/versions/{entry['object_version_id']}")
    assert exact.status_code == 200, exact.text
    assert (
        exact.json()["authorship"]["author_display_name"]
        == original["authorship"]["author_display_name"]
    )


def test_public_history_does_not_expose_hidden_structural_targets(client: TestClient) -> None:
    from test_catalogue_api import enable

    enable(client)
    project_id = create_project(client)
    target = create_object(client, project_id)
    response = client.post(
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "destination": {"kind": "project", "project_id": project_id},
            "snapshot": {
                "kind": "NOTE",
                "content": {
                    "title": "Attached note",
                    "content_md": "Analysis",
                    "assumptions_md": "None",
                    "reported_outcome": None,
                    "explanation_md": None,
                },
                "structural_relationships": [
                    {
                        "relationship_type": "ATTACHMENT",
                        "target_object_version_id": target["current_object_version_id"],
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    object_id = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "RESEARCH_OBJECT"
    )
    version_id = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    selection = {"project_id": project_id, "object_version_ids": [version_id]}
    preview = client.post("/api/v1/publication/preview", headers=headers("owner"), json=selection)
    assert preview.status_code == 200, preview.text
    published = client.post(
        "/api/v1/publication/confirm",
        headers=headers("owner"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Publish note",
        },
    )
    assert published.status_code == 201, published.text
    path = f"/api/v1/objects/{object_id}/versions"
    assert client.get(path).status_code == 200
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as session:
        session.add(SqlRecordModeration(object_id=UUID(target["id"]), hidden=True))
        session.commit()
    public = client.get(path)
    assert public.status_code == 404
    assert target["current_object_version_id"] not in public.text
    assert client.get(path, headers=headers("owner")).status_code == 200

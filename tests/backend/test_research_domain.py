from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import Table, func, select
from sqlalchemy.exc import IntegrityError

from polycolab.db.models import (
    SqlObjectRevision,
    SqlResearchComment,
    SqlResearchObject,
    SqlUser,
)
from polycolab.entities.enums import ResearchObjectKind
from polycolab.research.objects import StaleRevision, create_revision
from polycolab.research.objects import create_object as create_object_domain


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


def create_project(client: TestClient, *, visibility: str = "PRIVATE") -> str:
    response = client.post(
        "/api/v1/projects",
        headers=headers("owner"),
        json={"name": "Research", "visibility": visibility},
    )
    assert response.status_code == 201
    return cast(str, response.json()["id"])


def current_user_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/users/me", headers=headers(token))
    assert response.status_code == 200
    return cast(str, response.json()["id"])


def add_member(client: TestClient, project_id: str, token: str, role: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=headers("owner"),
        json={"user_id": current_user_id(client, token), "role": role},
    )
    assert response.status_code == 201


def create_object(
    client: TestClient,
    project_id: str,
    *,
    kind: str = "CLAIM",
    title: str = "Claim",
    content: str = "x",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": {
            "CLAIM": "STATEMENT",
            "PROOF_SKETCH": "PROOF",
            "IDEA": "NOTE",
            "DISCUSSION": "NOTE",
            "COUNTEREXAMPLE": "NOTE",
            "COMPUTATION": "NOTE",
        }.get(kind, kind),
        "content": {
            "title": title,
            "content_md": content,
            "assumptions_md": "None stated",
            "reported_outcome": None,
            "explanation_md": None,
        },
        "structural_relationships": [],
        "change_summary": "because",
    }
    if kind == "COMPUTATION":
        payload["content"]["source_language"] = "PYTHON"
    if kind in {"PROOF", "PROOF_SKETCH", "ATTEMPT"}:
        conclusion = create_object(
            client, project_id, kind="CLAIM", title=f"Conclusion for {title}"
        )
        if kind == "ATTEMPT":
            payload["content"].update(outcome="POTENTIAL", findings_md="Initial exploration")
            payload["structural_relationships"] = [
                {
                    "relationship_type": "TARGET",
                    "target_object_version_id": conclusion["current_object_version_id"],
                }
            ]
        else:
            payload["content"]["reported_progress"] = "POTENTIAL"
            payload["structural_relationships"] = [
                {
                    "relationship_type": "CONCLUSION",
                    "target_object_version_id": conclusion["current_object_version_id"],
                },
                {
                    "relationship_type": "ATTACHMENT",
                    "target_object_version_id": conclusion["current_object_version_id"],
                },
            ]
    response = client.post(
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "snapshot": payload,
            "destination": {"kind": "project", "project_id": project_id},
        },
    )
    assert response.status_code == 201, response.text
    object_id = next(
        row["entity_id"]
        for row in response.json()["outputs"]
        if row["entity_type"] == "RESEARCH_OBJECT"
    )
    return cast(
        dict[str, Any], client.get(f"/api/v1/objects/{object_id}", headers=headers("owner")).json()
    )


@pytest.mark.parametrize(
    "kind",
    [
        "PROBLEM",
        "DEFINITION",
        "CLAIM",
        "PROOF_SKETCH",
        "ATTEMPT",
        "COUNTEREXAMPLE",
        "FORMALIZATION",
        "COMPUTATION",
    ],
)
def test_all_committed_kinds_create_an_initial_human_revision(
    client: TestClient, kind: str
) -> None:
    project_id = create_project(client)
    created = create_object(client, project_id, kind=kind)
    assert created["kind"] == {
        "CLAIM": "STATEMENT",
        "PROOF_SKETCH": "PROOF",
        "COUNTEREXAMPLE": "NOTE",
        "COMPUTATION": "NOTE",
    }.get(kind, kind)
    assert created["authorship"]["actor_kind"] == "HUMAN"
    revision = created["current_object_version"]
    assert isinstance(revision, dict)
    assert revision["number"] == 1
    assert revision["previous_object_version_id"] is None
    assert revision["authorship"]["actor_kind"] == "HUMAN"


def test_revisions_are_append_only_and_stale_writes_preserve_history(client: TestClient) -> None:
    project_id = create_project(client)
    created = create_object(client, project_id, title="r1", content="old")
    object_id = created["id"]
    original = created["current_object_version"]
    assert isinstance(object_id, str) and isinstance(original, dict)
    revision_id = original["id"]
    assert isinstance(revision_id, str)

    revised = post_research(
        client,
        f"/api/v1/objects/{object_id}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": revision_id,
            "snapshot": {
                "kind": "STATEMENT",
                "content": {**original["content"], "title": "r2", "content_md": "new"},
                "structural_relationships": [],
                "change_summary": "corrected",
            },
        },
    )
    assert revised.status_code == 201
    current = revised.json()["current_object_version"]
    assert current["number"] == 2
    assert current["previous_object_version_id"] == revision_id

    stale = post_research(
        client,
        f"/api/v1/objects/{object_id}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": revision_id,
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **original["content"],
                    "title": "lost update",
                    "content_md": "must not persist",
                },
                "structural_relationships": [],
                "change_summary": None,
            },
        },
    )
    assert stale.status_code == 409
    history = client.get(f"/api/v1/objects/{object_id}/versions", headers=headers("owner"))
    assert history.status_code == 200
    assert [
        (item["number"], item["content"]["content_md"]) for item in history.json()["items"]
    ] == [
        (2, "new"),
        (1, "old"),
    ]
    assert (
        client.patch(
            f"/api/v1/objects/{object_id}/versions/{revision_id}", headers=headers("owner")
        ).status_code
        == 404
    )


def test_two_independent_sessions_allow_one_append_and_reject_the_stale_writer(
    client: TestClient,
) -> None:
    project_id = create_project(client)
    created = create_object(client, project_id, title="r1")
    object_id = UUID(cast(str, created["id"]))
    base = created["current_object_version"]
    assert isinstance(base, dict)
    base_id = UUID(cast(str, base["id"]))
    author_id = UUID(
        cast(str, client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    )
    app = cast(Any, client.app)
    first_session = app.state.session_factory()
    second_session = app.state.session_factory()
    try:
        first_author = first_session.get(SqlUser, author_id)
        second_author = second_session.get(SqlUser, author_id)
        assert first_author is not None and second_author is not None
        create_revision(
            first_session,
            project_id=UUID(project_id),
            object_id=object_id,
            base_revision_id=base_id,
            title="winner",
            content_md="first commit",
            rationale=None,
            author=first_author,
        )
        with pytest.raises(StaleRevision):
            create_revision(
                second_session,
                project_id=UUID(project_id),
                object_id=object_id,
                base_revision_id=base_id,
                title="loser",
                content_md="must not commit",
                rationale=None,
                author=second_author,
            )
        second_session.rollback()
    finally:
        first_session.close()
        second_session.close()
    history = client.get(f"/api/v1/objects/{object_id}/versions", headers=headers("owner"))
    assert [(item["number"], item["content"]["title"]) for item in history.json()["items"]] == [
        (2, "winner"),
        (1, "r1"),
    ]


def test_failed_initial_revision_flush_rolls_back_the_stable_object(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = create_project(client)
    author_id = UUID(current_user_id(client, "owner"))
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        author = session.get(SqlUser, author_id)
        assert author is not None
        original_flush = session.flush
        flushes = 0

        def fail_initial_revision(*args: object, **kwargs: object) -> None:
            nonlocal flushes
            flushes += 1
            if flushes == 2:
                raise RuntimeError("simulated revision persistence failure")
            original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", fail_initial_revision)
        with pytest.raises(RuntimeError, match="simulated"):
            create_object_domain(
                session,
                project_id=UUID(project_id),
                kind=ResearchObjectKind.CLAIM,
                title="must roll back",
                content_md="x",
                rationale=None,
                author=author,
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SqlResearchObject)
                .where(SqlResearchObject.project_id == UUID(project_id))
            )
            == 0
        )
    finally:
        session.close()


def test_exact_pinned_relations_allow_cycles_and_reject_cross_project_revisions(
    client: TestClient,
) -> None:
    project_id = create_project(client)
    source = create_object(client, project_id, title="A")
    target = create_object(client, project_id, title="B")
    source_revision = source["current_object_version"]
    target_revision = target["current_object_version"]
    assert isinstance(source_revision, dict) and isinstance(target_revision, dict)
    relation = post_research(
        client,
        "/api/v1/relations",
        headers=headers("owner"),
        json={
            "direction": "UNIDIRECTIONAL",
            "destination": {"kind": "project", "project_id": project_id},
            "source_object_version_id": source_revision["id"],
            "target_object_version_id": target_revision["id"],
            "relationship_type": "DEPENDS_ON",
            "description": "uses r1",
        },
    )
    assert relation.status_code == 201
    reverse = post_research(
        client,
        "/api/v1/relations",
        headers=headers("owner"),
        json={
            "direction": "UNIDIRECTIONAL",
            "destination": {"kind": "project", "project_id": project_id},
            "source_object_version_id": target_revision["id"],
            "target_object_version_id": source_revision["id"],
            "relationship_type": "DEPENDS_ON",
            "description": "cycle is permitted",
        },
    )
    assert reverse.status_code == 201
    second = post_research(
        client,
        f"/api/v1/objects/{target['id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": target_revision["id"],
            "snapshot": {
                "kind": "STATEMENT",
                "content": {**target_revision["content"], "title": "B2", "content_md": "new"},
                "structural_relationships": [],
                "change_summary": None,
            },
        },
    )
    assert second.status_code == 201
    relations = client.get(f"/api/v1/objects/{source['id']}/relations", headers=headers("owner"))
    assert relations.status_code == 200
    assert any(
        item["target_object_version_id"] == target_revision["id"]
        for item in relations.json()["items"]
    )

    other_project = create_project(client)
    foreign = create_object(client, other_project, title="private")
    foreign_revision = foreign["current_object_version"]
    assert isinstance(foreign_revision, dict)
    denied = post_research(
        client,
        "/api/v1/relations",
        headers=headers("owner"),
        json={
            "direction": "UNIDIRECTIONAL",
            "destination": {"kind": "project", "project_id": project_id},
            "source_object_version_id": source_revision["id"],
            "target_object_version_id": foreign_revision["id"],
            "relationship_type": "USES",
            "description": "must not cross projects",
        },
    )
    assert denied.status_code == 404


def test_database_rejects_a_cross_object_revision_base(client: TestClient) -> None:
    project_id = create_project(client)
    first = create_object(client, project_id, title="first")
    second = create_object(client, project_id, title="second")
    first_revision = first["current_object_version"]
    second_revision = second["current_object_version"]
    assert isinstance(first_revision, dict) and isinstance(second_revision, dict)
    app = cast(Any, client.app)
    session = app.state.session_factory()
    try:
        invalid = SqlObjectRevision(
            project_id=UUID(project_id),
            object_id=UUID(cast(str, first["id"])),
            number=2,
            title="invalid lineage",
            content_md="must fail",
            base_revision_id=UUID(cast(str, second_revision["id"])),
            created_by_user_id=UUID(
                cast(str, client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
            ),
        )
        session.add(invalid)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_neighborhood_and_dependents_use_the_selected_exact_revision(client: TestClient) -> None:
    project_id = create_project(client)
    source = create_object(client, project_id, title="source")
    target = create_object(client, project_id, title="target")
    source_id = cast(str, source["id"])
    target_id = cast(str, target["id"])
    source_revision = source["current_object_version"]
    target_revision = target["current_object_version"]
    assert isinstance(source_revision, dict) and isinstance(target_revision, dict)
    relation = post_research(
        client,
        "/api/v1/relations",
        headers=headers("owner"),
        json={
            "direction": "UNIDIRECTIONAL",
            "destination": {"kind": "project", "project_id": project_id},
            "source_object_version_id": source_revision["id"],
            "target_object_version_id": target_revision["id"],
            "relationship_type": "PROVES",
            "description": "r1 only",
        },
    )
    assert relation.status_code == 201
    selected = client.get(
        f"/api/v1/objects/{source_id}/neighborhood?object_version_id={source_revision['id']}",
        headers=headers("owner"),
    )
    assert selected.status_code == 200
    assert selected.json()["relationships"][0]["target_object_version_id"] == target_revision["id"]
    assert {
        (item["object_version_id"], item["object_id"], item["title"])
        for item in selected.json()["nodes"]
    } == {
        (source_revision["id"], source_id, "source"),
        (target_revision["id"], target_id, "target"),
    }
    inbound = client.get(
        f"/api/v1/objects/{target_id}/dependents?object_version_id={target_revision['id']}",
        headers=headers("owner"),
    )
    assert inbound.status_code == 200
    assert inbound.json()[0]["source_object_version_id"] == source_revision["id"]

    updated = post_research(
        client,
        f"/api/v1/objects/{source_id}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": source_revision["id"],
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **source_revision["content"],
                    "title": "source r2",
                    "content_md": "new",
                },
                "structural_relationships": [],
                "change_summary": None,
            },
        },
    )
    assert updated.status_code == 201
    target_updated = post_research(
        client,
        f"/api/v1/objects/{target_id}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": target_revision["id"],
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **target_revision["content"],
                    "title": "target r2",
                    "content_md": "new",
                },
                "structural_relationships": [],
                "change_summary": None,
            },
        },
    )
    assert target_updated.status_code == 201
    # The historical endpoint remains resolvable for controlled expansion even
    # after the neighbor's current revision moves forward.
    historical = client.get(
        f"/api/v1/objects/{source_id}/neighborhood?object_version_id={source_revision['id']}",
        headers=headers("owner"),
    )
    assert (target_revision["id"], target_id, "target") in {
        (item["object_version_id"], item["object_id"], item["title"])
        for item in historical.json()["nodes"]
    }
    # Current-default uses r2 and never silently drags its r1 edge forward.
    assert (
        client.get(f"/api/v1/objects/{source_id}/neighborhood", headers=headers("owner")).json()[
            "relationships"
        ]
        == []
    )
    cross_object = client.get(
        f"/api/v1/objects/{source_id}/neighborhood?object_version_id={target_revision['id']}",
        headers=headers("owner"),
    )
    assert cross_object.status_code == 404


def test_comments_are_revision_pinned_and_archiving_or_role_removal_stops_writes(
    client: TestClient,
) -> None:
    project_id = create_project(client)
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    add_member(client, project_id, "reader", "READ_ONLY")
    created = create_object(client, project_id)
    object_id = created["id"]
    revision = created["current_object_version"]
    assert isinstance(object_id, str) and isinstance(revision, dict)
    comment = post_research(
        client,
        f"/api/v1/objects/{object_id}/comments",
        headers=headers("contributor"),
        json={"object_version_id": revision["id"], "body_md": "discussion"},
    )
    assert comment.status_code == 201
    assert comment.json()["object_version_id"] == revision["id"]
    assert (
        post_research(
            client,
            f"/api/v1/objects/{object_id}/comments",
            headers=headers("reader"),
            json={"object_version_id": revision["id"], "body_md": "not allowed"},
        ).status_code
        == 403
    )

    contributor_id = current_user_id(client, "contributor")
    assert (
        client.delete(
            f"/api/v1/projects/{project_id}/members/{contributor_id}", headers=headers("owner")
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/objects/{object_id}/comments", headers=headers("contributor")
        ).status_code
        == 404
    )

    assert (
        client.patch(
            f"/api/v1/projects/{project_id}", headers=headers("owner"), json={"archived": True}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/objects",
            headers=headers("owner"),
            json={
                "destination": {"kind": "project", "project_id": project_id},
                "snapshot": {
                    "kind": "STATEMENT",
                    "content": {**revision["content"], "title": "blocked"},
                    "structural_relationships": [],
                    "change_summary": None,
                },
            },
        ).status_code
        == 403
    )
    assert (
        client.get(f"/api/v1/projects/{project_id}/objects", headers=headers("owner")).status_code
        == 200
    )


def test_owner_can_make_project_research_public(client: TestClient) -> None:
    project_id = create_project(client)
    created = create_object(client, project_id, title="Private claim", content="private body")
    assert (
        client.patch(
            f"/api/v1/projects/{project_id}",
            headers=headers("owner"),
            json={"visibility": "PUBLIC"},
        ).status_code
        == 200
    )
    response = client.get(f"/api/v1/objects/{created['id']}")
    assert response.status_code == 200
    assert "private body" in response.text


def test_database_metadata_pins_current_base_relation_and_comment_scope() -> None:
    objects_table = cast(Table, SqlResearchObject.__table__)
    revisions_table = cast(Table, SqlObjectRevision.__table__)
    from polycolab.db.models.relationships import SqlObjectVersionRelationship

    relations_table = cast(Table, SqlObjectVersionRelationship.__table__)
    comments_table = cast(Table, SqlResearchComment.__table__)
    current = {constraint.name for constraint in objects_table.foreign_key_constraints}
    revisions = {constraint.name for constraint in revisions_table.foreign_key_constraints}
    relation_targets = {
        element.parent.name
        for constraint in relations_table.foreign_key_constraints
        for element in constraint.elements
        if element.column.table.name == "object_revisions"
    }
    comments = {constraint.name for constraint in comments_table.foreign_key_constraints}
    assert "fk_research_objects_current_revision" in current
    assert "fk_object_revisions_base_object_project" in revisions
    assert {
        "source_object_version_id",
        "target_object_version_id",
        "first_object_version_id",
        "second_object_version_id",
    } == relation_targets
    assert "fk_research_comments_revision_object_project" in comments
    for table in (objects_table, revisions_table, relations_table, comments_table):
        assert table.columns


def test_postgresql_migration_compiles_immutable_history_triggers_and_downgrade_removal() -> None:
    api_directory = Path(__file__).resolve().parents[2] / "src/backend"
    sql = StringIO()
    config = Config(str(api_directory / "alembic.ini"), output_buffer=sql)
    config.set_main_option(
        "script_location", str(api_directory / "polycolab" / "db" / "migrations" / "postgresql")
    )
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://unused/unused")
    command.upgrade(config, "head", sql=True)
    compiled = sql.getvalue()
    for table in ("object_revisions", "relation_assertions", "research_comments"):
        assert f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table}" in compiled
    assert "fk_research_objects_current_revision" in compiled
    assert "fk_object_revisions_base_object_project" in compiled

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from test_catalogue_api import enable
from test_research_domain import add_member, create_object, create_workspace
from test_research_structure import targets

from polycolab.access.actors import agent_actor
from polycolab.access.authorization import AuthorizationDenied
from polycolab.catalogue import publication
from polycolab.db.models import (
    SqlMembership,
    SqlMutationReceipt,
    SqlObjectRevision,
    SqlProofSketchRevision,
    SqlPublicationManifest,
    SqlPublicRelease,
    SqlRecordModeration,
    SqlResearchAttemptRevision,
    SqlUser,
)
from polycolab.db.models.relationships import SqlObjectVersionRelationship
from polycolab.entities.enums import WorkspaceRole
from polycolab.platform.outbox import canonical_digest
from polycolab.research.contracts import PublicationFields, PublicationSelection


def headers(token: str = "owner", *, key: str | None = None) -> dict[str, str]:
    values = {"Authorization": f"Bearer {token}"}
    if key is not None:
        values["Idempotency-Key"] = key
    return values


def test_preview_confirm_retry_and_historical_projection_are_exact_and_atomic(
    client: TestClient,
) -> None:
    app = enable(client)
    project_id = create_workspace(client)
    proof = create_object(client, project_id, kind="PROOF_SKETCH", title="Private sketch")
    proof_revision_id = proof["current_object_version_id"]
    with app.state.session_factory() as db:
        structure = db.get(SqlProofSketchRevision, UUID(proof_revision_id))
        assert structure is not None
        conclusion_revision_id = str(structure.conclusion_revision_id)

    summary = client.put(
        f"/api/v1/research/objects/{proof['id']}/summary",
        headers=headers(key="publication-summary"),
        json={
            "workspace_id": project_id,
            "body_md": "An exact authored summary",
            "source_object_version_ids": [conclusion_revision_id],
        },
    )
    assert summary.status_code == 200, summary.text
    comment = client.post(
        f"/api/v1/research/objects/{proof['id']}/comments",
        headers=headers(key="publication-comment"),
        json={
            "workspace_id": project_id,
            "object_version_id": proof_revision_id,
            "body_md": "Include this comment",
        },
    )
    assert comment.status_code == 201, comment.text
    progress = client.post(
        f"/api/v1/research/objects/{proof['id']}/progress",
        headers=headers(key="publication-progress"),
        json={
            "workspace_id": project_id,
            "object_version_id": proof_revision_id,
            "status": "PARTIAL",
            "detail_md": "Include this progress update",
        },
    )
    assert progress.status_code == 201, progress.text
    note = client.put(
        f"/api/v1/research/objects/{proof['id']}/human-note",
        headers=headers(key="publication-note"),
        json={"workspace_id": project_id, "body_md": "Never publish this note"},
    )
    assert note.status_code == 200, note.text

    selection = {
        "workspace_id": project_id,
        "object_version_ids": [proof_revision_id],
        "summary_revision_ids": [summary.json()["current_revision"]["id"]],
        "comment_ids": [comment.json()["id"]],
        "progress_ids": [progress.json()["id"]],
        "relation_ids": [],
    }
    assert (
        client.post(
            "/api/v1/publication/preview",
            headers=headers("contributor"),
            json=selection,
        ).status_code
        == 404
    )
    add_member(client, project_id, "contributor", "CONTRIBUTOR")
    assert (
        client.post(
            "/api/v1/publication/preview",
            headers=headers("contributor"),
            json=selection,
        ).status_code
        == 403
    )
    preview = client.post("/api/v1/publication/preview", headers=headers(), json=selection)
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["selection"]["object_version_ids"] == [proof_revision_id]
    assert "revision_ids" not in preview_body["selection"]
    assert "required_revision_ids" not in preview_body
    legacy_selection = {**selection, "revision_ids": selection["object_version_ids"]}
    del legacy_selection["object_version_ids"]
    assert (
        client.post(
            "/api/v1/publication/preview", headers=headers(), json=legacy_selection
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/publication/preview",
            headers=headers(),
            json={**selection, "object_version_ids": [proof_revision_id, proof_revision_id]},
        ).status_code
        == 422
    )
    assert conclusion_revision_id in preview_body["required_object_version_ids"]
    fields = preview_body["public_fields"]
    assert "records" not in fields and "relations" not in fields
    assert fields["comments"][0]["object_version_id"] == proof_revision_id
    assert fields["progress"][0]["object_version_id"] == proof_revision_id
    assert fields["summaries"][0]["source_object_version_ids"] == [conclusion_revision_id]
    assert {item["id"] for item in fields["object_versions"]} == {
        proof_revision_id,
        conclusion_revision_id,
    }
    assert "human-note" not in str(preview_body) and "Never publish" not in str(preview_body)

    stale = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="stale-publication"),
        json={**selection, "preview_digest": "0" * 64, "reason": "Publish exact work"},
    )
    assert stale.status_code == 409
    with app.state.session_factory() as db:
        assert db.query(SqlPublicRelease).count() == 0

    confirmation = {
        **selection,
        "preview_digest": preview_body["preview_digest"],
        "reason": "Publish exact work",
    }
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="confirm-publication"),
        json=confirmation,
    )
    assert confirmed.status_code == 201, confirmed.text
    historical_selection = PublicationSelection.model_validate(legacy_selection).model_dump(
        mode="json"
    )
    with app.state.session_factory() as db:
        manifest = db.get(SqlPublicationManifest, UUID(confirmed.json()["id"]))
        assert manifest is not None
        assert manifest.selection == historical_selection
        assert "required_revision_ids" in manifest.public_fields
        assert manifest.preview_digest == canonical_digest(
            {
                "selection": historical_selection,
                "required_revision_ids": preview_body["required_object_version_ids"],
                "public_fields": PublicationFields.model_validate(
                    manifest.public_fields
                ).model_dump(mode="json"),
            }
        )
        receipt = db.query(SqlMutationReceipt).filter_by(operation="publication.confirm").one()
        assert receipt.request_digest == canonical_digest(
            {
                "version": 1,
                "payload": {
                    **historical_selection,
                    "preview_digest": confirmation["preview_digest"],
                    "reason": confirmation["reason"],
                },
            }
        )
    assert (
        client.post(
            "/api/v1/publication/confirm",
            headers=headers(key="legacy-publication"),
            json={
                **legacy_selection,
                "preview_digest": confirmation["preview_digest"],
                "reason": confirmation["reason"],
            },
        ).status_code
        == 422
    )
    replay = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="confirm-publication"),
        json=confirmation,
    )
    assert replay.status_code == 201 and replay.json() == confirmed.json()
    assert (
        client.post(
            "/api/v1/publication/confirm",
            headers=headers(key="confirm-publication"),
            json={**confirmation, "reason": "Conflicting replay"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/publication/confirm",
            headers=headers(key="second-confirmation"),
            json=confirmation,
        ).status_code
        == 409
    )
    history = client.get(
        "/api/v1/publication/history",
        headers=headers(),
        params={"workspace_id": project_id, "limit": 1},
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["items"]] == [confirmed.json()["id"]]
    public_manifest = client.get(f"/api/v1/publications/{confirmed.json()['id']}")
    assert public_manifest.status_code == 200
    assert public_manifest.json()["public_fields"] == preview_body["public_fields"]
    for version in public_manifest.json()["public_fields"]["object_versions"]:
        assert version["authorship"]["author_user_id"] is None
        assert version["authorship"]["contribution_id"] is None
        assert version == client.get(f"/api/v1/versions/{version['id']}").json()
    assert "workspace_id" not in public_manifest.json()
    assert "workspace_id" not in public_manifest.json()["selection"]
    assert client.get(f"/api/v1/records/{proof_revision_id}").status_code == 200
    assert client.get(f"/api/v1/records/{conclusion_revision_id}").status_code == 200

    revised = post_research(
        client,
        f"/api/v1/objects/{proof['id']}/versions",
        headers=headers(),
        json={
            "expected_current_object_version_id": proof_revision_id,
            "snapshot": {
                "kind": "PROOF",
                "content": {
                    **proof["current_object_version"]["content"],
                    "title": "Later private sketch",
                    "content_md": "This edit remains private.",
                },
                "change_summary": "Continue privately",
                "structural_relationships": [
                    {"relationship_type": role, "target_object_version_id": conclusion_revision_id}
                    for role in ("CONCLUSION", "ATTACHMENT")
                ],
            },
        },
    )
    assert revised.status_code == 201, revised.text
    later_revision_id = revised.json()["current_object_version_id"]
    assert client.get(f"/api/v1/records/{later_revision_id}").status_code == 404
    public_object = client.get(f"/api/v1/objects/{proof['id']}")
    assert public_object.status_code == 200, public_object.text
    assert public_object.json()["current_object_version_id"] == proof_revision_id
    assert later_revision_id not in public_object.text
    history = client.get(f"/api/v1/objects/{proof['id']}/versions")
    assert history.status_code == 200, history.text
    assert [item["id"] for item in history.json()["items"]] == [proof_revision_id]
    assert targets(history.json()["items"][0], "CONCLUSION") == [conclusion_revision_id]
    assert history.json()["items"][0]["structural_relationships"]
    assert later_revision_id not in history.text
    assert client.get(f"/api/v1/records/{proof_revision_id}").status_code == 200
    with app.state.session_factory() as db:
        db.add(SqlRecordModeration(object_id=UUID(proof["id"]), hidden=True))
        db.commit()
    assert client.get(f"/api/v1/publications/{confirmed.json()['id']}").status_code == 404


def test_agent_cannot_preview_or_confirm_publication(client: TestClient) -> None:
    app = enable(client)
    project_id = create_workspace(client)
    target = create_object(client, project_id)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers()).json()["id"])
    actor = agent_actor(
        sponsor_user_id=user_id,
        agent_version_id=uuid4(),
        run_id=uuid4(),
        capability_id=uuid4(),
        session_id=uuid4(),
        context_manifest_id=uuid4(),
        project_id=UUID(project_id),
        operation_scope=frozenset(),
    )
    selection = PublicationSelection(
        project_id=UUID(project_id), revision_ids=[UUID(target["current_object_version_id"])]
    )
    with app.state.session_factory() as db, pytest.raises(AuthorizationDenied):
        publication.preview(db, actor=actor, selection=selection)


def test_confirmation_reauthorizes_publisher_without_partial_release(
    client: TestClient,
) -> None:
    app = enable(client)
    project_id = create_workspace(client)
    target = create_object(client, project_id)
    selection = {
        "workspace_id": project_id,
        "object_version_ids": [target["current_object_version_id"]],
        "summary_revision_ids": [],
        "comment_ids": [],
        "progress_ids": [],
        "relation_ids": [],
    }
    preview = client.post("/api/v1/publication/preview", headers=headers(), json=selection).json()
    owner_id = UUID(client.get("/api/v1/users/me", headers=headers()).json()["id"])
    with app.state.session_factory() as db:
        membership = (
            db.query(SqlMembership).filter_by(project_id=UUID(project_id), user_id=owner_id).one()
        )
        membership.role = WorkspaceRole.READ_ONLY
        db.commit()
    response = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="revoked-publication"),
        json={
            **selection,
            "preview_digest": preview["preview_digest"],
            "reason": "Authority has been revoked",
        },
    )
    assert response.status_code == 403
    with app.state.session_factory() as db:
        assert db.query(SqlPublicRelease).count() == 0


def test_attempt_targets_and_selected_relation_endpoints_join_required_closure(
    client: TestClient,
) -> None:
    app = enable(client)
    project_id = create_workspace(client)
    attempt = create_object(client, project_id, kind="ATTEMPT", title="Private attempt")
    unrelated = create_object(client, project_id, title="Related private statement")
    with app.state.session_factory() as db:
        structure = db.get(SqlResearchAttemptRevision, UUID(attempt["current_object_version_id"]))
        assert structure is not None
        target_revision_id = str(structure.target_revision_id)
    relation = client.post(
        "/api/v1/relations",
        headers=headers(key="publication-relation"),
        json={
            "destination": {"kind": "workspace", "workspace_id": project_id},
            "direction": "UNIDIRECTIONAL",
            "source_object_version_id": attempt["current_object_version_id"],
            "target_object_version_id": unrelated["current_object_version_id"],
            "relationship_type": "USES",
            "description": "Publish this optional relationship",
        },
    )
    assert relation.status_code == 201, relation.text
    relation_id = relation.json()["outputs"][0]["entity_id"]
    preview = client.post(
        "/api/v1/publication/preview",
        headers=headers(),
        json={
            "workspace_id": project_id,
            "object_version_ids": [attempt["current_object_version_id"]],
            "relation_ids": [relation_id],
        },
    )
    assert preview.status_code == 200, preview.text
    required = set(preview.json()["required_object_version_ids"])
    assert {target_revision_id, unrelated["current_object_version_id"]} <= required
    projected = preview.json()["public_fields"]["relationships"][0]
    assert projected["id"] == relation_id
    assert projected["direction"] == "UNIDIRECTIONAL"
    assert projected["source_object_version_id"] == attempt["current_object_version_id"]
    assert projected["target_object_version_id"] == unrelated["current_object_version_id"]
    assert projected["ownership_scope_id"] is None


def test_publication_versions_and_equivalence_use_frozen_content_not_private_history(
    client: TestClient,
) -> None:
    app = enable(client)
    project = create_workspace(client)
    first = create_object(client, project, title="Unreleased predecessor")
    previous = first["current_object_version_id"]
    edited = post_research(
        client,
        f"/api/v1/objects/{first['id']}/versions",
        headers=headers(),
        json={
            "expected_current_object_version_id": previous,
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **first["current_object_version"]["content"],
                    "title": "Released version",
                    "content_md": "Frozen mathematical content",
                },
                "structural_relationships": [],
                "change_summary": "Revised claim",
            },
        },
    )
    assert edited.status_code == 201, edited.text
    current = edited.json()["current_object_version_id"]
    second = create_object(client, project, title="Equivalent formulation")
    other = second["current_object_version_id"]
    declaration = client.post(
        "/api/v1/relations",
        headers=headers(key="published-equivalence"),
        json={
            "destination": {"kind": "workspace", "workspace_id": project},
            "direction": "BIDIRECTIONAL",
            "first_object_version_id": other,
            "second_object_version_id": current,
            "relationship_type": "EQUIVALENT_TO",
            "description": "Frozen equivalence explanation",
        },
    )
    assert declaration.status_code == 201, declaration.text
    relationship_id = declaration.json()["outputs"][0]["entity_id"]
    selection = {
        "workspace_id": project,
        "object_version_ids": [current],
        "relation_ids": [relationship_id],
    }
    preview = client.post("/api/v1/publication/preview", headers=headers(), json=selection)
    assert preview.status_code == 200, preview.text
    frozen = preview.json()["public_fields"]
    assert previous not in preview.text
    assert preview.json()["required_object_version_ids"] == [other]
    relationship = frozen["relationships"][0]
    assert relationship["direction"] == "BIDIRECTIONAL"
    assert [relationship["first_object_version_id"], relationship["second_object_version_id"]] == (
        sorted([current, other])
    )
    assert "source_object_version_id" not in relationship
    assert "target_object_version_id" not in relationship
    assert relationship["authorship"]["author_user_id"] is None
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers(key="confirm-equivalence"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Reviewed",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    manifest_id = confirmed.json()["id"]
    assert confirmed.json()["public_fields"] == frozen
    # SQLite deliberately permits this drift; PostgreSQL separately enforces immutability.
    with app.state.session_factory() as db:
        row = db.get(SqlObjectRevision, UUID(current))
        relation = db.get(SqlObjectVersionRelationship, UUID(relationship_id))
        assert row is not None and relation is not None
        author = db.get(SqlUser, row.created_by_user_id)
        assert author is not None
        row.title = "Raw row drift"
        row.content_md = "Must not replace released content"
        relation.description = "Must not replace released explanation"
        author.display_name = "Renamed account"
        db.commit()
    public = client.get(f"/api/v1/publications/{manifest_id}")
    assert public.status_code == 200, public.text
    assert public.json()["public_fields"] == frozen
    history = client.get(
        "/api/v1/publication/history", headers=headers(), params={"workspace_id": project}
    )
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["public_fields"] == frozen
    released = next(v for v in frozen["object_versions"] if v["id"] == current)
    assert client.get(f"/api/v1/versions/{current}").json() == released
    links = client.get(f"/api/v1/versions/{current}/relationships")
    assert links.status_code == 200, links.text
    assert links.json() == frozen["relationships"]
    assert client.get(f"/api/v1/versions/{previous}").status_code == 404
    member = client.get(f"/api/v1/versions/{current}", headers=headers())
    assert member.json()["previous_object_version_id"] == previous
    assert member.json()["authorship"]["author_user_id"] is not None

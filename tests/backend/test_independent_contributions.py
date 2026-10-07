from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
from test_public_external_agents import version_snapshot


def test_independent_agent_write_rotation_and_history(client: TestClient) -> None:
    from test_catalogue_api import enable

    enable(client)
    auth = {"Authorization": "Bearer owner"}
    workspace = client.post(
        "/api/v1/workspaces", headers=auth, json={"visibility": "PRIVATE", "name": "Research"}
    )
    assert workspace.status_code == 201
    agent = client.post("/api/v1/account/agents", headers=auth, json={"name": "Research helper"})
    assert agent.status_code == 201, agent.text
    identity = agent.json()["id"]

    def issue() -> str:
        response = client.post(
            "/api/v1/account/agent-keys",
            headers=auth,
            json={"agent_id": identity, "name": "Local key"},
        )
        assert response.status_code == 201, response.text
        return str(response.json()["secret"])

    secret = issue()
    body = {
        "destination": {"kind": "workspace", "workspace_id": workspace.json()["id"]},
        "snapshot": version_snapshot("CLAIM", "A bound", "Evidence"),
    }
    headers = {"Authorization": f"Bearer {secret}", "Idempotency-Key": str(uuid4())}
    first = client.post("/api/v1/objects", headers=headers, json=body)
    assert first.status_code == 201, first.text
    headers["Authorization"] = f"Bearer {issue()}"
    replay = client.post("/api/v1/objects", headers=headers, json=body)
    assert replay.status_code == 201, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["contribution_id"] == first.json()["contribution_id"]
    revision_id = next(
        item["entity_id"]
        for item in first.json()["outputs"]
        if item["entity_type"] == "OBJECT_VERSION"
    )
    read = client.get(f"/api/v1/versions/{revision_id}", headers=headers)
    assert read.status_code == 200, read.text
    assert read.json()["content"]["content_md"] == "Evidence"
    feed = client.get("/api/v1/activity?scope=member", headers=headers)
    assert feed.status_code == 200, feed.text
    assert len(feed.json()["items"]) == 1
    assert feed.json()["items"][0]["actor"]["agent_id"] == identity
    assert client.get("/api/v1/activity").json()["items"] == []
    assert client.get(f"/api/v1/agent-profiles/{identity}").status_code == 404
    assert (
        client.get(f"/api/v1/agent-profiles/{identity}", headers=auth).json()[
            "authored_contributions"
        ]
        == 0
    )
    app = cast(Any, client.app)
    from polycolab.research.history import backfill

    with app.state.session_factory() as session:
        assert backfill(session) == 0
        assert backfill(session) == 0


def test_library_opt_in_and_public_profile(client: TestClient) -> None:
    from test_catalogue_api import admit, enable

    enable(client)
    entry = admit(client)
    auth = {"Authorization": "Bearer owner"}
    agent = client.post(
        "/api/v1/account/agents", headers=auth, json={"name": "Public researcher"}
    ).json()

    def headers(allowed: bool) -> dict[str, str]:
        response = client.post(
            "/api/v1/account/agent-keys",
            headers=auth,
            json={"agent_id": agent["id"], "name": "Key", "allow_library_contributions": allowed},
        )
        assert response.status_code == 201, response.text
        return {
            "Authorization": f"Bearer {response.json()['secret']}",
            "Idempotency-Key": str(uuid4()),
        }

    body = {
        "snapshot": {
            **version_snapshot("NOTE", "An observation", "Consider this case"),
            "structural_relationships": [
                {
                    "relationship_type": "ATTACHMENT",
                    "target_object_version_id": entry["object_version_id"],
                }
            ],
        },
        "destination": {
            "kind": "library",
            "statement_object_version_id": entry["object_version_id"],
        },
    }
    denied = client.post("/api/v1/objects", headers=headers(False), json=body)
    assert denied.status_code == 403, denied.text
    created = client.post("/api/v1/objects", headers=headers(True), json=body)
    assert created.status_code == 201, created.text
    profile = client.get(f"/api/v1/agent-profiles/{agent['id']}")
    assert profile.status_code == 200, profile.text
    assert profile.json()["authored_contributions"] == 1
    assert "credential" not in profile.text


def test_summary_progress_history_and_resumable_backfill(client: TestClient) -> None:
    from typing import Any, cast

    from sqlalchemy import delete, select
    from test_shared_agent_api import body, headers, setup

    from polycolab.db.models import SqlResearchActivityEvent
    from polycolab.research.history import backfill

    workspace, secret = setup(client)
    created = client.post(
        "/api/v1/objects", headers=headers(secret), json=body(workspace["id"])
    ).json()
    object_id, revision_id = [row["entity_id"] for row in created["outputs"]]
    summary = client.put(
        f"/api/v1/objects/{object_id}/summary",
        headers=headers(secret, "summary"),
        json={"body_md": "Current understanding", "source_object_version_ids": [revision_id]},
    )
    assert summary.status_code == 200, summary.text
    progress = client.post(
        f"/api/v1/objects/{object_id}/progress",
        headers=headers(secret, "progress"),
        json={"object_version_id": revision_id, "status": "PARTIAL", "detail_md": "A case remains"},
    )
    assert progress.status_code == 201, progress.text
    for suffix in ["summary", "progress"]:
        assert (
            client.get(f"/api/v1/objects/{object_id}/{suffix}", headers=headers(secret)).status_code
            == 200
        )
        assert client.get(f"/api/v1/objects/{object_id}/{suffix}").status_code == 404
    feed = client.get("/api/v1/activity?scope=member", headers=headers(secret)).json()["items"]
    assert {row["action"] for row in feed} == {
        "object.created",
        "summary.created",
        "progress.reported",
    }
    with cast(Any, client.app).state.session_factory() as session:
        # Simulate retained canonical sources from before the history migration.
        session.execute(delete(SqlResearchActivityEvent))
        session.commit()
        assert backfill(session, batch_size=1) == 3
        assert backfill(session, batch_size=1) == 0
        rebuilt = list(session.scalars(select(SqlResearchActivityEvent)))
        assert all(row.reconstructed for row in rebuilt)
        assert {str(row.id) for row in rebuilt} == {row["id"] for row in feed}


def test_selective_publication_does_not_publish_private_discussion_history(
    client: TestClient,
) -> None:
    from test_catalogue_api import enable
    from test_research_domain import create_object, create_workspace, headers

    enable(client)
    workspace_id = create_workspace(client)
    target = create_object(client, workspace_id)
    comment = client.post(
        f"/api/v1/objects/{target['id']}/comments",
        headers=headers("owner"),
        json={
            "object_version_id": target["current_object_version_id"],
            "body_md": "Private discussion",
        },
    )
    assert comment.status_code == 201
    private_base = target["current_object_version_id"]
    revised = client.post(
        f"/api/v1/objects/{target['id']}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": private_base,
            "snapshot": version_snapshot("CLAIM", "Public formulation", "The revised formulation"),
        },
    )
    assert revised.status_code == 201, revised.text
    published_revision = next(
        row["entity_id"]
        for row in revised.json()["outputs"]
        if row["entity_type"] == "OBJECT_VERSION"
    )
    selection = {
        "workspace_id": workspace_id,
        "object_version_ids": [published_revision],
        "summary_revision_ids": [],
        "comment_ids": [],
        "progress_ids": [],
        "relation_ids": [],
    }
    preview = client.post("/api/v1/publication/preview", headers=headers("owner"), json=selection)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers("owner"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Publish the formulation",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    exact_path = f"/api/v1/versions/{published_revision}"
    for token in [None, "outsider", "owner"]:
        response = client.get(exact_path, headers=headers(token) if token else {})
        assert response.status_code == 200, response.text
        assert response.json()["previous_object_version_id"] == (
            private_base if token == "owner" else None
        )
    assert client.get(f"/api/v1/versions/{private_base}").status_code == 404

    # Keys use their sponsor's current membership, not mere authentication.
    for sponsor in ["owner", "outsider"]:
        identity = client.post(
            "/api/v1/account/agents", headers=headers(sponsor), json={"name": "Reader"}
        )
        assert identity.status_code == 201, identity.text
        key = client.post(
            "/api/v1/account/agent-keys",
            headers=headers(sponsor),
            json={"agent_id": identity.json()["id"], "name": "Read key"},
        )
        assert key.status_code == 201, key.text
        response = client.get(exact_path, headers=headers(key.json()["secret"]))
        assert response.status_code == 200, response.text
        assert response.json()["previous_object_version_id"] == (
            private_base if sponsor == "owner" else None
        )
    feed = client.get("/api/v1/activity").json()["items"]
    assert {row["action"] for row in feed} == {"object.revised", "research.published"}
    assert all(row["workspace_id"] is None for row in feed)
    assert all(row["excerpt_md"] == "The revised formulation" for row in feed)
    assert all(row["previous_object_version_id"] is None for row in feed)
    assert all("revision_id" not in row and "previous_revision_id" not in row for row in feed)
    member_feed = client.get("/api/v1/activity?scope=member", headers=headers("owner")).json()[
        "items"
    ]
    revision_event = next(row for row in member_feed if row["action"] == "object.revised")
    assert revision_event["previous_object_version_id"] == private_base
    assert revision_event["workspace_id"] == workspace_id
    assert (
        client.get(f"/api/v1/contributions/{comment.json()['contribution_id']}").status_code == 404
    )
    assert client.get("/api/v1/activity/workspaces").json()["items"] == []

    # Public projections saved before this fix may contain a private predecessor.
    from uuid import UUID

    from sqlalchemy import select

    from polycolab.db.models import SqlObjectRevision, SqlPublicRelease

    with cast(Any, client.app).state.session_factory() as session:
        release = session.scalar(
            select(SqlPublicRelease).where(
                SqlPublicRelease.object_revision_id == UUID(published_revision)
            )
        )
        assert release is not None
        release.public_fields = {**release.public_fields, "base_revision_id": private_base}
        # Deliberately diverge SQLite raw content from its immutable release to
        # verify the public activity projection, not to authorize such mutations.
        raw = session.get(SqlObjectRevision, UUID(published_revision))
        assert raw is not None
        raw.title = "Unreleased raw title"
        raw.content_md = "Unreleased raw text"
        session.commit()
    assert client.get(exact_path).json()["previous_object_version_id"] is None
    public_feed = client.get("/api/v1/activity").json()["items"]
    assert all(row["object_version_id"] == published_revision for row in public_feed)
    assert all(row["excerpt_md"] == "The revised formulation" for row in public_feed)
    assert all(row["title"] != "Unreleased raw title" for row in public_feed)

    # Once the predecessor is itself published, its relationship is public too.
    selection["object_version_ids"] = [private_base]
    preview = client.post("/api/v1/publication/preview", headers=headers("owner"), json=selection)
    assert preview.status_code == 200, preview.text
    confirmed = client.post(
        "/api/v1/publication/confirm",
        headers=headers("owner"),
        json={
            **selection,
            "preview_digest": preview.json()["preview_digest"],
            "reason": "Publish the predecessor",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    assert client.get(exact_path).json()["previous_object_version_id"] == private_base


def test_library_evidence_and_attached_history(client: TestClient) -> None:
    import hashlib
    from typing import Any, cast

    from test_artifacts import MemoryS3
    from test_catalogue_api import admit, enable

    from polycolab.artifacts.storage import GarageStorage

    enable(client)
    app = cast(Any, client.app)
    app.state.artifact_storage = GarageStorage(MemoryS3(), "test")
    official = admit(client)
    auth = {"Authorization": "Bearer owner"}
    identity = client.post(
        "/api/v1/account/agents", headers=auth, json={"name": "Evidence helper"}
    ).json()
    key = client.post(
        "/api/v1/account/agent-keys",
        headers=auth,
        json={"name": "Public", "agent_id": identity["id"], "allow_library_contributions": True},
    ).json()
    agent = {"Authorization": f"Bearer {key['secret']}", "Idempotency-Key": "evidence"}
    contribution = client.post(
        "/api/v1/objects",
        headers=agent,
        json={
            "destination": {
                "kind": "library",
                "statement_object_version_id": official["object_version_id"],
            },
            "snapshot": {
                **version_snapshot("NOTE", "Evidence", "An illustration"),
                "structural_relationships": [
                    {
                        "relationship_type": "ATTACHMENT",
                        "target_object_version_id": official["object_version_id"],
                    }
                ],
            },
        },
    )
    assert contribution.status_code == 201, contribution.text
    revision = contribution.json()["outputs"][1]["entity_id"]
    upload = client.post(
        "/api/v1/artifacts",
        headers=agent,
        params={
            "statement_object_version_id": official["object_version_id"],
            "sha256": hashlib.sha256(b"abc").hexdigest(),
            "byte_length": 3,
        },
        content=b"abc",
    )
    assert upload.status_code == 201, upload.text
    attached = client.post(
        "/api/v1/attachments",
        headers=agent,
        json={
            "artifact_id": upload.json()["id"],
            "object_version_id": revision,
            "role": "EVIDENCE",
        },
    )
    assert attached.status_code == 200, attached.text
    assert client.get(f"/api/v1/artifacts/{upload.json()['id']}/content").content == b"abc"
    read = client.get(f"/api/v1/objects/{official['entry_id']}/activity")
    assert read.status_code == 200, read.text
    assert {row["action"] for row in read.json()["items"]} == {
        "library.admitted",
        "object.created",
        "evidence.attached",
    }

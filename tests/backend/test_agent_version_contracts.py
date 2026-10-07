"""Live agent version contracts preserve historical grants and exact context."""

import hashlib
import json
from uuid import UUID

from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, headers
from test_direct_contributions import active_run
from test_proposals_api import _proposal_run
from test_research_domain import create_object, create_workspace

from polycolab.agents.context import manifest_for_run
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlContextManifest,
    SqlObjectRevision,
    SqlRunWriteGrant,
)
from polycolab.platform.outbox import canonical_digest


def test_live_grant_request_replays_historical_encoding_and_rejects_legacy_fields(
    client: TestClient,
) -> None:
    app, _, run_id, _, _ = active_run(client, public=True)
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, run_id)
        grant = db.get(SqlRunWriteGrant, run_id)
        assert run is not None and grant is not None
        message = db.get(SqlAgentMessage, run.request_message_id)
        assert message is not None
        stored = dict(grant.request)
        digest = grant.request_digest
        assert digest == canonical_digest(stored)
        assert "public_target_revision_ids" in stored
        assert "public_target_object_version_ids" not in stored
        authority = dict(stored)
        authority["public_target_object_version_ids"] = authority.pop("public_target_revision_ids")
        body = {
            "client_request_id": str(run.client_request_id),
            "content_md": message.content_md,
            "gateway_profile_id": str(run.gateway_profile_id),
            "context_object_version_ids": list(run.requested_context_revision_ids),
            "context_artifact_ids": list(run.requested_context_artifact_ids),
            "requested_authority": authority,
        }
        path = f"/api/v1/agent-sessions/{run.session_id}/messages"
    replay = client.post(path, headers=headers(), json=body)
    assert replay.status_code == 202, replay.text
    assert replay.json()["run"]["id"] == str(run_id)
    assert (
        client.post(path, headers=headers(), json={**body, "context_revision_ids": []}).status_code
        == 422
    )
    assert (
        client.post(
            path, headers=headers(), json={**body, "requested_authority": stored}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path,
            headers=headers(),
            json={**body, "requested_authority": {**authority, "max_mutations": 4}},
        ).status_code
        == 409
    )
    with app.state.session_factory() as db:
        grant = db.get(SqlRunWriteGrant, run_id)
        assert grant is not None and grant.request == stored and grant.request_digest == digest
        assert db.query(SqlAgentRun).count() == 1


def test_context_manifest_uses_typed_private_and_frozen_public_versions(
    client: TestClient,
) -> None:
    app = enable(client)
    public = admit(client)
    project = create_workspace(client)
    private = create_object(client, project, title="Private source")
    public_id = public["object_version_id"]
    private_id = private["current_object_version_id"]
    _, run_id = _proposal_run(client, project, [private_id, public_id])
    expected_public = client.get(f"/api/v1/versions/{public_id}").json()
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        manifest_id = manifest.id
        stored_ids, stored_digest = list(manifest.revision_ids), manifest.digest
        assert stored_ids == sorted([private_id, public_id])
        assert (
            stored_digest
            == hashlib.sha256(
                json.dumps(
                    {"version": 2, "revision_ids": stored_ids, "artifact_ids": []},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        row = db.get(SqlObjectRevision, UUID(public_id))
        assert row is not None
        row.title = "Raw title must not replace frozen public input"
        db.commit()
    path = f"/api/v1/agent-runs/{run_id}/context"
    response = client.get(path, headers=headers())
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["object_version_ids"] == stored_ids
    assert "revision_ids" not in value and "revisions" not in value
    versions = {item["id"]: item for item in value["object_versions"]}
    assert versions[public_id] == expected_public
    assert (
        versions[private_id]
        == client.get(f"/api/v1/versions/{private_id}", headers=headers()).json()
    )
    assert versions[public_id]["authorship"]["author_user_id"] is None
    assert versions[private_id]["authorship"]["author_user_id"] is not None
    assert client.get(path, headers=headers("outsider")).status_code == 404
    with app.state.session_factory() as db:
        saved = db.get(SqlContextManifest, manifest_id)
        assert (
            saved is not None and saved.revision_ids == stored_ids and saved.digest == stored_digest
        )

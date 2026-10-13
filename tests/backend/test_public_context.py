"""Public inputs remain exact pins and lose access even in cached manifests."""

from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from test_catalogue_api import admit, enable, headers
from test_proposals_api import _proposal_run

from polycolab.agents.context import ContextInvalid, manifest_for_run, manifest_revisions
from polycolab.agents.sessions import claim_next_run, start_claimed_run
from polycolab.agents.tools import ToolCapabilityInvalid, execute_tool, issue_tool_capability
from polycolab.db.models import SqlAgentRun, SqlCatalogueEntry


def test_cached_public_context_rechecks_moderation(client: TestClient) -> None:
    app = enable(client)
    entry = admit(client)
    project = client.post(
        "/api/v1/projects", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    _, run_id = _proposal_run(client, project["id"], [entry["object_version_id"]])
    with app.state.session_factory() as db:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        assert manifest.revision_ids == [entry["object_version_id"]]
        original_digest = manifest.digest
        assert len(manifest_revisions(db, manifest=manifest)) == 1
        value = db.get(SqlCatalogueEntry, UUID(entry["entry_id"]))
        assert value is not None
        value.hidden = True
        db.commit()
        with pytest.raises(ContextInvalid):
            manifest_revisions(db, manifest=manifest)
        with pytest.raises(ContextInvalid):
            manifest_for_run(db, run=run)
        assert manifest.digest == original_digest


def test_live_tools_use_version_contract_even_for_older_agent_definitions(
    client: TestClient,
) -> None:
    app = enable(client)
    entry = admit(client)
    project = client.post(
        "/api/v1/projects", headers=headers(), json={"visibility": "PRIVATE", "name": "Private"}
    ).json()
    _proposal_run(client, project["id"], [entry["object_version_id"]])
    with app.state.session_factory() as db:
        claimed = claim_next_run(db, worker_id="v1-check", lease_for=timedelta(seconds=60))
        assert claimed is not None
        run = start_claimed_run(
            db, run_id=claimed.id, worker_id="v1-check", lease_generation=claimed.lease_generation
        )
        manifest = manifest_for_run(db, run=run)
        token = issue_tool_capability(
            db, run=run, manifest=manifest, ttl_seconds=60, lease_generation=run.lease_generation
        )
        response = execute_tool(
            db,
            token=token,
            name="get_object_version",
            arguments={"object_version_id": entry["object_version_id"]},
        )
        assert response["id"] == entry["object_version_id"]
        assert "content" in response
        assert response["previous_object_version_id"] is None
        assert response["structural_relationships"] == []
        assert response["omitted_structural_relationship_count"] == 0
        assert "revision_id" not in response
        context = execute_tool(db, token=token, name="get_context", arguments={})
        assert isinstance(context["object_versions"], list)
        assert context["object_versions"] == [response]
        with pytest.raises(ToolCapabilityInvalid):
            execute_tool(
                db,
                token=token,
                name="get_object_revision",
                arguments={"revision_id": entry["object_version_id"]},
            )
        with pytest.raises(ToolCapabilityInvalid):
            execute_tool(
                db,
                token=token,
                name="get_object_version",
                arguments={"revision_id": entry["object_version_id"]},
            )

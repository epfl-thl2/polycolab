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
from test_version_contracts import snapshot

import polycolab.agents.proposals as proposals_domain
from polycolab.agents.context import manifest_for_run
from polycolab.agents.proposals import submit_proposal
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlContributionEnvelope,
    SqlProposal,
    SqlProposalChange,
    SqlProposalChangeDecision,
    SqlProposalDecisionBatch,
    SqlRelationAssertion,
    SqlResearchComment,
    SqlResearchObject,
)
from polycolab.entities.enums import AgentRunEventKind


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def version_proposal(title: str, content: str) -> dict[str, Any]:
    value = snapshot()
    value["content"].update(title=title, content_md=content)
    return {"kind": "CREATE_OBJECT", "snapshot": value}


def _project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/v1/workspaces", headers=headers("owner"), json={"visibility": "PRIVATE", "name": "P"}
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def _profile(client: TestClient, token: str = "owner") -> dict[str, object]:
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=headers(token),
        json={
            "display_name": "Model",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "model",
            "api_key": "test-secret",
        },
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


def _member(client: TestClient, project_id: str, token: str, role: str) -> None:
    user = client.get("/api/v1/users/me", headers=headers(token)).json()
    response = client.post(
        f"/api/v1/workspaces/{project_id}/members",
        headers=headers("owner"),
        json={"user_id": user["id"], "role": role},
    )
    assert response.status_code == 201


def _proposal_run(
    client: TestClient, project_id: str, context_ids: list[str] | None = None
) -> tuple[str, str]:
    profile = _profile(client)
    agent_session = client.post(
        "/api/v1/agent-sessions",
        headers=headers("owner"),
        json={"workspace_id": project_id, "agent_kind": "RESEARCHER"},
    ).json()
    queued = client.post(
        f"/api/v1/agent-sessions/{agent_session['id']}/messages",
        headers=headers("owner"),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "Review.",
            "gateway_profile_id": profile["id"],
            "context_object_version_ids": context_ids or [],
        },
    )
    assert queued.status_code == 202, queued.text
    return cast(str, agent_session["id"]), cast(str, queued.json()["run"]["id"])


def _proposal_source_event(db: Any, run: SqlAgentRun, invocation: str) -> list[int]:
    event = SqlAgentRunEvent(
        run_id=run.id,
        cursor=1,
        idempotency_key=f"{invocation}-requested",
        kind=AgentRunEventKind.TOOL_REQUESTED,
        payload={"tool_name": "submit_proposal"},
    )
    db.add(event)
    db.commit()
    return [event.cursor]


def _submit_object_proposal(client: TestClient, project_id: str) -> tuple[str, str]:
    session_id, run_id = _proposal_run(client, project_id)
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        source_event_cursors = _proposal_source_event(db, run, "object-v1")
        proposal = submit_proposal(
            db,
            project_id=UUID(project_id),
            session_id=UUID(session_id),
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            idempotency_key="object-v1",
            summary="Make a claim",
            changes=[
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "CLAIM",
                    "title": "Agent claim",
                    "content_md": "x",
                }
            ],
            trusted_source_event_cursors=source_event_cursors,
            trusted_source_invocation_key="object-v1",
        )
        change_id = db.scalar(select(SqlProposal.id).where(SqlProposal.id == proposal.id))
        assert change_id is not None
        return str(proposal.id), str(proposal.id)
    finally:
        db.close()


def test_proposals_are_member_reviewable_but_context_stays_with_private_run_owner(
    client: TestClient,
) -> None:
    project_id = str(_project(client)["id"])
    _member(client, project_id, "contributor", "CONTRIBUTOR")
    _member(client, project_id, "reader", "READ_ONLY")
    proposal_id, _ = _submit_object_proposal(client, project_id)
    detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("contributor"))
    assert detail.status_code == 200
    change_id = detail.json()["changes"][0]["id"]
    assert (
        client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("reader")).status_code == 403
    )
    assert (
        client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("outsider")).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/proposals/{proposal_id}/context", headers=headers("contributor")
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/proposals/{proposal_id}/context", headers=headers("owner")).status_code
        == 200
    )

    accepted = client.post(
        f"/api/v1/proposals/{proposal_id}/changes/{change_id}/accept",
        headers={**headers("contributor"), "Idempotency-Key": "accept-claim-v1"},
        json={},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "ACCEPTED"
    replay = client.post(
        f"/api/v1/proposals/{proposal_id}/changes/{change_id}/accept",
        headers={**headers("contributor"), "Idempotency-Key": "accept-claim-v1"},
        json={},
    )
    assert replay.status_code == 200
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/changes/{change_id}/accept",
            headers={**headers("contributor"), "Idempotency-Key": "other-key"},
            json={},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/changes/{change_id}/accept",
            headers={**headers("contributor"), "Idempotency-Key": "accept-claim-v1"},
            json={"payload": version_proposal("different claim", "different")},
        ).status_code
        == 409
    )
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        assert db.scalar(select(func.count()).select_from(SqlResearchObject)) == 1
    finally:
        db.close()


def test_stale_revision_proposal_returns_current_base_without_mutating_research(
    client: TestClient,
) -> None:
    project_id = str(_project(client)["id"])
    initial = post_research(
        client,
        "/api/v1/objects",
        headers=headers("owner"),
        json={
            "destination": {"kind": "workspace", "workspace_id": project_id},
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    "title": "r1",
                    "content_md": "old",
                    "assumptions_md": "None stated",
                    "reported_outcome": None,
                    "explanation_md": None,
                },
                "structural_relationships": [],
            },
        },
    )
    assert initial.status_code == 201
    object_id = initial.json()["id"]
    base_id = initial.json()["current_object_version_id"]
    session_id, run_id = _proposal_run(client, project_id, [base_id])
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        source_event_cursors = _proposal_source_event(db, run, "revision-v1")
        proposal = submit_proposal(
            db,
            project_id=UUID(project_id),
            session_id=UUID(session_id),
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            idempotency_key="revision-v1",
            summary="Improve the claim",
            changes=[
                {
                    "kind": "CREATE_REVISION",
                    "object_id": object_id,
                    "base_revision_id": base_id,
                    "title": "agent r2",
                    "content_md": "agent",
                }
            ],
            trusted_source_event_cursors=source_event_cursors,
            trusted_source_invocation_key="revision-v1",
        )
        proposal_id = str(proposal.id)
    finally:
        db.close()
    human = post_research(
        client,
        f"/api/v1/objects/{object_id}/versions",
        headers=headers("owner"),
        json={
            "expected_current_object_version_id": base_id,
            "snapshot": {
                "kind": "STATEMENT",
                "content": {
                    **initial.json()["current_object_version"]["content"],
                    "title": "human r2",
                    "content_md": "human",
                },
                "structural_relationships": [],
            },
        },
    )
    assert human.status_code == 201
    detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("owner")).json()
    stale = client.post(
        f"/api/v1/proposals/{proposal_id}/changes/{detail['changes'][0]['id']}/accept",
        headers={**headers("owner"), "Idempotency-Key": "stale-revision-v1"},
        json={},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "stale_proposal"
    assert (
        stale.json()["error"]["current_object_version_id"]
        == human.json()["current_object_version_id"]
    )
    assert "current_revision_id" not in stale.json()["error"]
    revisions = client.get(f"/api/v1/objects/{object_id}/versions", headers=headers("owner"))
    assert [item["content"]["title"] for item in revisions.json()["items"]] == ["human r2", "r1"]


def test_proposal_id_does_not_cross_project_membership_boundary(client: TestClient) -> None:
    first_project_id = str(_project(client)["id"])
    second_project_id = str(_project(client)["id"])
    _member(client, second_project_id, "contributor", "CONTRIBUTOR")
    proposal_id, _ = _submit_object_proposal(client, first_project_id)
    assert (
        client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("contributor")).status_code
        == 404
    )


def test_removed_member_loses_proposal_list_detail_and_batch_decision_access(
    client: TestClient,
) -> None:
    project_id = str(_project(client)["id"])
    _member(client, project_id, "contributor", "CONTRIBUTOR")
    proposal_id, _ = _submit_object_proposal(client, project_id)
    detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("owner")).json()
    contributor_id = client.get("/api/v1/users/me", headers=headers("contributor")).json()["id"]
    assert (
        client.delete(
            f"/api/v1/workspaces/{project_id}/members/{contributor_id}", headers=headers("owner")
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/api/v1/workspaces/{project_id}/proposals", headers=headers("contributor")
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("contributor")).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/decisions",
            headers={**headers("contributor"), "Idempotency-Key": "revoked-v1"},
            json={"decisions": [{"change_id": detail["changes"][0]["id"], "action": "REJECT"}]},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/proposals/{proposal_id}/context", headers=headers("contributor")
        ).status_code
        == 404
    )


def test_decision_idempotency_requires_matching_key_action_and_normalized_reason(
    client: TestClient,
) -> None:
    project_id = str(_project(client)["id"])
    proposal_id, _ = _submit_object_proposal(client, project_id)
    change_id = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("owner")).json()[
        "changes"
    ][0]["id"]
    missing_key = client.post(
        f"/api/v1/proposals/{proposal_id}/changes/{change_id}/reject",
        headers=headers("owner"),
        json={"reason": "not yet"},
    )
    assert missing_key.status_code == 422
    request: dict[str, Any] = {
        "headers": {**headers("owner"), "Idempotency-Key": "reject-claim-v1"},
        "json": {"reason": "not yet"},
    }
    rejected = client.post(f"/api/v1/proposals/{proposal_id}/changes/{change_id}/reject", **request)
    assert rejected.status_code == 200
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/changes/{change_id}/reject", **request
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/changes/{change_id}/reject",
            headers={**headers("owner"), "Idempotency-Key": "reject-claim-v1"},
            json={"reason": "different"},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/changes/{change_id}/accept",
            headers={**headers("owner"), "Idempotency-Key": "reject-claim-v1"},
            json={},
        ).status_code
        == 409
    )


def test_selected_proposal_decisions_are_atomic_and_replay_as_one_batch(client: TestClient) -> None:
    project_id = str(_project(client)["id"])
    session_id, run_id = _proposal_run(client, project_id)
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        proposal = submit_proposal(
            db,
            project_id=UUID(project_id),
            session_id=UUID(session_id),
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            idempotency_key="batch-v1",
            summary="Several alternatives",
            trusted_source_event_cursors=_proposal_source_event(db, run, "batch-v1"),
            trusted_source_invocation_key="batch-v1",
            changes=[
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "CLAIM",
                    "title": "accept",
                    "content_md": "a",
                },
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "CLAIM",
                    "title": "edit",
                    "content_md": "b",
                },
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "ATTEMPT",
                    "title": "reject",
                    "content_md": "c",
                    "attempt": {
                        "target_revision_id": str(uuid4()),
                        "outcome": "FAILED",
                        "findings_md": "Rejected attempt",
                        "evidence": [],
                    },
                },
            ],
        )
        change_ids = [
            str(item.id)
            for item in db.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == proposal.id)
                .order_by(SqlProposalChange.ordinal)
            )
        ]
        proposal_id = str(proposal.id)
    finally:
        db.close()
    body = {
        "decisions": [
            {"change_id": change_ids[0], "action": "ACCEPT"},
            {
                "change_id": change_ids[1],
                "action": "ACCEPT",
                "payload": version_proposal("edited", "edited content"),
            },
            {"change_id": change_ids[2], "action": "REJECT", "reason": "not useful"},
        ]
    }
    request: dict[str, Any] = {
        "headers": {**headers("owner"), "Idempotency-Key": "batch-decision-v1"},
        "json": body,
    }
    decided = client.post(f"/api/v1/proposals/{proposal_id}/decisions", **request)
    assert decided.status_code == 200, decided.text
    assert [item["status"] for item in decided.json()] == ["ACCEPTED", "ACCEPTED", "REJECTED"]
    assert client.post(f"/api/v1/proposals/{proposal_id}/decisions", **request).status_code == 200
    assert (
        client.post(
            f"/api/v1/proposals/{proposal_id}/decisions",
            headers={**headers("owner"), "Idempotency-Key": "batch-decision-v1"},
            json={"decisions": body["decisions"][:2]},
        ).status_code
        == 409
    )
    objects = client.get(f"/api/v1/workspaces/{project_id}/objects", headers=headers("owner"))
    assert {
        item["current_object_version"]["content"]["title"] for item in objects.json()["items"]
    } == {
        "accept",
        "edited",
    }
    first_object = next(
        item
        for item in objects.json()["items"]
        if item["current_object_version"]["content"]["title"] == "accept"
    )
    assert (
        client.patch(
            f"/api/v1/workspaces/{project_id}",
            headers=headers("owner"),
            json={"visibility": "PUBLIC"},
        ).status_code
        == 200
    )
    public = client.get(f"/api/v1/objects/{first_object['id']}")
    assert public.status_code == 200
    assert all(
        value not in public.text
        for value in (str(run_id), str(session_id), "context_manifest", "source_event")
    )
    provenance = client.get(
        f"/api/v1/workspaces/{project_id}/contributions/RESEARCH_OBJECT/{first_object['id']}",
        headers=headers("owner"),
    )
    assert provenance.status_code == 200
    assert set(provenance.json()) == {
        "canonical_entity_id",
        "canonical_entity_type",
        "deciding_user_id",
        "created_at",
    }
    version_id = first_object["current_object_version_id"]
    version_path = f"/api/v1/workspaces/{project_id}/contributions/OBJECT_VERSION/{version_id}"
    version_provenance = client.get(version_path, headers=headers("owner"))
    assert version_provenance.status_code == 200, version_provenance.text
    assert version_provenance.json()["canonical_entity_type"] == "OBJECT_VERSION"
    assert version_provenance.json()["canonical_entity_id"] == version_id
    assert client.get(version_path).status_code in (401, 404)
    assert client.get(version_path, headers=headers("outsider")).status_code == 404
    assert (
        client.get(
            version_path.replace("OBJECT_VERSION", "OBJECT_REVISION"), headers=headers("owner")
        ).status_code
        == 422
    )


def test_relation_and_comment_proposals_apply_as_canonical_agent_contributions(
    client: TestClient,
) -> None:
    from test_research_domain import create_object

    project_id = str(_project(client)["id"])
    source = create_object(client, project_id, title="Source", content="s")
    target = create_object(client, project_id, kind="DEFINITION", title="Target", content="t")
    source_revision = source["current_object_version_id"]
    target_revision = target["current_object_version_id"]
    session_id, run_id = _proposal_run(client, project_id, [source_revision, target_revision])
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        proposal = submit_proposal(
            db,
            project_id=UUID(project_id),
            session_id=UUID(session_id),
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            idempotency_key="relation-comment-v1",
            summary="Connect and discuss",
            trusted_source_event_cursors=_proposal_source_event(db, run, "relation-comment-v1"),
            trusted_source_invocation_key="relation-comment-v1",
            changes=[
                {
                    "kind": "CREATE_RELATION",
                    "source_revision_id": source_revision,
                    "target_revision_id": target_revision,
                    "relation_type": "USES",
                    "rationale": "uses the definition",
                },
                {
                    "kind": "CREATE_COMMENT",
                    "object_id": source["id"],
                    "revision_id": source_revision,
                    "body_md": "Agent review note.",
                },
            ],
        )
        change_ids = [
            str(item.id)
            for item in db.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == proposal.id)
                .order_by(SqlProposalChange.ordinal)
            )
        ]
        proposal_id = str(proposal.id)
    finally:
        db.close()
    decided = client.post(
        f"/api/v1/proposals/{proposal_id}/decisions",
        headers={**headers("owner"), "Idempotency-Key": "relation-comment-decision-v1"},
        json={
            "decisions": [
                {"change_id": change_ids[0], "action": "ACCEPT"},
                {"change_id": change_ids[1], "action": "ACCEPT"},
            ]
        },
    )
    assert decided.status_code == 200, decided.text
    assert [item["status"] for item in decided.json()] == ["ACCEPTED", "ACCEPTED"]
    for change, entity_type in zip(
        decided.json(), ("OBJECT_VERSION_RELATIONSHIP", "RESEARCH_COMMENT"), strict=True
    ):
        provenance = client.get(
            f"/api/v1/workspaces/{project_id}/contributions/{entity_type}/{change['applied_entity_id']}",
            headers=headers("owner"),
        )
        assert provenance.status_code == 200, provenance.text
        assert provenance.json()["canonical_entity_type"] == entity_type
    db = app.state.session_factory()
    try:
        assert db.scalar(select(func.count()).select_from(SqlRelationAssertion)) == 1
        assert db.scalar(select(func.count()).select_from(SqlResearchComment)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.actor_kind == "AGENT")
            )
            == 2
        )
    finally:
        db.close()


def test_mid_batch_application_failure_rolls_back_every_decision_and_entity(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_id = str(_project(client)["id"])
    session_id, run_id = _proposal_run(client, project_id)
    app = cast(Any, client.app)
    db = app.state.session_factory()
    try:
        run = db.get(SqlAgentRun, UUID(run_id))
        assert run is not None
        manifest = manifest_for_run(db, run=run)
        proposal = submit_proposal(
            db,
            project_id=UUID(project_id),
            session_id=UUID(session_id),
            run_id=run.id,
            agent_version_id=run.agent_version_id,
            context_manifest_id=manifest.id,
            idempotency_key="rollback-v1",
            summary="Two objects",
            trusted_source_event_cursors=_proposal_source_event(db, run, "rollback-v1"),
            trusted_source_invocation_key="rollback-v1",
            changes=[
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "CLAIM",
                    "title": "first",
                    "content_md": "a",
                },
                {
                    "kind": "CREATE_OBJECT",
                    "object_kind": "CLAIM",
                    "title": "second",
                    "content_md": "b",
                },
            ],
        )
        proposal_id = str(proposal.id)
        change_ids = [
            str(item.id)
            for item in db.scalars(
                select(SqlProposalChange)
                .where(SqlProposalChange.proposal_id == proposal.id)
                .order_by(SqlProposalChange.ordinal)
            )
        ]
    finally:
        db.close()
    original_apply = proposals_domain._apply_change
    calls = 0

    def fail_second(*args: object, **kwargs: object) -> tuple[UUID, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated second change failure")
        return original_apply(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(proposals_domain, "_apply_change", fail_second)
    failed = client.post(
        f"/api/v1/proposals/{proposal_id}/decisions",
        headers={**headers("owner"), "Idempotency-Key": "rollback-decision-v1"},
        json={
            "decisions": [
                {"change_id": change_ids[0], "action": "ACCEPT"},
                {"change_id": change_ids[1], "action": "ACCEPT"},
            ]
        },
    )
    assert failed.status_code == 500
    detail = client.get(f"/api/v1/proposals/{proposal_id}", headers=headers("owner")).json()
    assert [item["status"] for item in detail["changes"]] == ["PENDING", "PENDING"]
    db = app.state.session_factory()
    try:
        assert db.scalar(select(func.count()).select_from(SqlResearchObject)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.actor_kind == "AGENT")
            )
            == 0
        )
        assert db.scalar(select(func.count()).select_from(SqlProposalChangeDecision)) == 0
        assert db.scalar(select(func.count()).select_from(SqlProposalDecisionBatch)) == 0
    finally:
        db.close()


def test_proposal_metadata_and_postgresql_migration_preserve_scoped_integrity() -> None:
    proposal_changes_table = cast(Table, SqlProposalChange.__table__)
    proposals_table = cast(Table, SqlProposal.__table__)
    contributions_table = cast(Table, SqlContributionEnvelope.__table__)
    decisions_table = cast(Table, SqlProposalChangeDecision.__table__)
    batches_table = cast(Table, SqlProposalDecisionBatch.__table__)
    assert {
        "ck_proposal_changes_ordinal",
        "ck_proposal_changes_type",
        "ck_proposal_changes_status",
        "ck_proposal_changes_decision",
        "fk_proposal_changes_proposal_project",
    } <= {item.name for item in proposal_changes_table.constraints}
    assert {
        "fk_proposals_manifest_scope",
        "fk_proposals_session_project",
        "fk_proposals_run_session_scope",
    } <= {item.name for item in proposals_table.constraints}
    assert {
        "ck_contribution_review",
        "fk_contribution_manifest_binding",
        "ck_contribution_envelopes_actor_kind",
        "ck_contribution_envelopes_actor_scope",
        "fk_contribution_run_binding",
    } <= {item.name for item in contributions_table.constraints}
    assert {
        "uq_proposal_change_decisions_change",
        "uq_proposal_change_decisions_change_key",
        "fk_proposal_change_decisions_change_project",
        "ck_proposal_change_decisions_action",
        "ck_proposal_change_decisions_digest_length",
    } <= {item.name for item in decisions_table.constraints}
    assert {
        "uq_proposal_decision_batches_key",
        "fk_proposal_decision_batches_proposal_project",
        "ck_proposal_decision_batches_digest_length",
    } <= {item.name for item in batches_table.constraints}
    api_directory = Path(__file__).resolve().parents[2] / "backend"
    sql = StringIO()
    config = Config(str(api_directory / "alembic.ini"), output_buffer=sql)
    config.set_main_option(
        "script_location", str(api_directory / "polycolab" / "db" / "migrations" / "postgresql")
    )
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://unused/unused")
    command.upgrade(config, "head", sql=True)
    compiled = sql.getvalue()
    for constraint in (
        "uq_agent_runs_scope",
        "fk_context_manifests_run_scope",
        "fk_run_tool_capabilities_manifest_scope",
        "ck_run_tool_capabilities_lease_generation",
        "ck_agent_run_events_kind",
        "fk_proposals_manifest_scope",
        "ck_proposal_changes_decision",
        "fk_contribution_manifest_binding",
        "uq_proposal_change_decisions_change_key",
        "fk_proposal_change_decisions_change_project",
        "uq_agent_runs_full_scope",
        "fk_proposals_run_session_scope",
        "fk_contribution_run_binding",
        "proposal_decision_batches",
        "proposal_change_decisions_immutable",
        "contribution_envelopes_immutable",
    ):
        assert constraint in compiled

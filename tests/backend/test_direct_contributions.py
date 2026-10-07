"""Hosted writes preserve exact output scope and trusted retry provenance."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from research_requests import post_research
from sqlalchemy import func, select
from test_catalogue_api import admit, enable, headers
from test_library_api import attempt_payload
from test_proposals_api import _profile

from polycolab.agents.context import manifest_for_run
from polycolab.agents.sessions import append_worker_event, claim_next_run, start_claimed_run
from polycolab.agents.tools import ToolCapabilityInvalid, execute_tool, issue_tool_capability
from polycolab.db.models import (
    SqlAgentRun,
    SqlAgentRunEvent,
    SqlContributionEnvelope,
    SqlRunRevisionOutput,
)
from polycolab.entities.enums import AgentRunEventKind
from polycolab.entities.time import utc_now
from polycolab.research import direct_contributions


def active_run(
    client: TestClient,
    *,
    public: bool,
    project_id: str | None = None,
    allowed_operations: list[str] | None = None,
    context_revision_ids: list[str] | None = None,
    context_artifact_ids: list[str] | None = None,
    requested_tool_name: str = "write_object_version",
) -> tuple[Any, str, UUID, dict[str, Any], dict[str, Any]]:
    app = enable(client)
    app.state.settings.feature_agent_execution_enabled = True
    entry = admit(client)
    project = (
        client.get(f"/api/v1/workspaces/{project_id}", headers=headers()).json()
        if project_id
        else client.post(
            "/api/v1/workspaces",
            headers=headers(),
            json={"visibility": "PRIVATE", "name": "Research"},
        ).json()
    )
    profile = _profile(client)
    parent = client.post(
        "/api/v1/agent-sessions",
        headers=headers(),
        json={
            "workspace_id": project["id"],
            "agent_kind": "RESEARCHER",
            "agent_version": 2,
        },
    ).json()
    authority = {
        "destination": "PUBLIC" if public else "WORKSPACE",
        "allowed_operations": allowed_operations
        or [
            "CREATE_RECORD",
            "CREATE_RELATION",
            "WRITE_SUMMARY",
            "COMMENT",
            "REPORT_PROGRESS",
        ],
        "max_mutations": 5,
        **(
            {
                "public_target_object_version_ids": [entry["object_version_id"]],
                "public_task_md": "Explore this public statement",
            }
            if public
            else {}
        ),
    }
    queued = client.post(
        f"/api/v1/agent-sessions/{parent['id']}/messages",
        headers=headers(),
        json={
            "client_request_id": str(uuid4()),
            "content_md": "PRIVATE CHAT MUST NOT BE PUBLIC",
            "gateway_profile_id": profile["id"],
            "context_object_version_ids": context_revision_ids or [entry["object_version_id"]],
            "context_artifact_ids": context_artifact_ids or [],
            "requested_authority": authority,
        },
    )
    assert queued.status_code == 202, queued.text
    run_id = UUID(queued.json()["run"]["id"])
    with app.state.session_factory() as db:
        claimed = claim_next_run(db, worker_id="direct-test", lease_for=timedelta(seconds=60))
        assert claimed is not None
        run = start_claimed_run(
            db, run_id=run_id, worker_id="direct-test", lease_generation=claimed.lease_generation
        )
        manifest = manifest_for_run(db, run=run)
        token = issue_tool_capability(db, run=run, manifest=manifest, ttl_seconds=60)
        append_worker_event(
            db,
            worker_id="direct-test",
            lease_generation=run.lease_generation,
            run_id=run.id,
            kind=AgentRunEventKind.TOOL_REQUESTED,
            idempotency_key="direct-1-requested",
            payload={"tool_name": requested_tool_name},
        )
    return app, token, run_id, entry, project


@pytest.mark.parametrize("public", [False, True])
def test_direct_record_retry_and_exact_output_read(client: TestClient, public: bool) -> None:
    app, token, run_id, entry, project = active_run(client, public=public)
    payload = attempt_payload(entry["object_version_id"], None if public else project["id"])
    content = payload["snapshot"]["content"]
    content.update(
        assumptions_md="Finite connected graph",
        reported_outcome="FAILED",
        explanation_md="A stronger hypothesis is needed",
    )
    if not public:
        payload["snapshot"]["kind"] = "STATEMENT"
        content["statement_label"] = "CLAIM"
        content.pop("outcome")
        content.pop("findings_md")
        payload["snapshot"]["structural_relationships"] = [
            pin
            for pin in payload["snapshot"]["structural_relationships"]
            if pin["relationship_type"] == "ATTACHMENT"
        ]
    with app.state.session_factory() as db:
        cursor = db.scalar(
            select(SqlAgentRunEvent.cursor).where(
                SqlAgentRunEvent.run_id == run_id,
                SqlAgentRunEvent.idempotency_key == "direct-1-requested",
            )
        )
        assert cursor is not None

        def write() -> dict[str, object]:
            return execute_tool(
                db,
                token=token,
                name="write_object_version",
                arguments=payload,
                idempotency_key="direct-1",
                source_event_cursor=cursor,
            )

        first = write()
        assert write() == first
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlRunRevisionOutput)
                .where(SqlRunRevisionOutput.run_id == run_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.run_id == run_id)
            )
            == 1
        )
        output = execute_tool(
            db,
            token=token,
            name="get_object_version",
            arguments={"object_version_id": first["object_version_id"]},
        )
        expected_content = (
            {**content, "attached_object_ids": [entry["entry_id"]]} if public else content
        )
        assert output["content"] == expected_content
        assert "run_id" not in str(output)
        context = execute_tool(db, token=token, name="get_context", arguments={})
        values = context["object_versions"]
        assert isinstance(values, list)
        source = next(value for value in values if value["id"] == entry["object_version_id"])
        assert source["catalogue"]["source"]["locator"] == "Conjecture 3, p. 7"
        with pytest.raises(ToolCapabilityInvalid):
            execute_tool(
                db,
                token=token,
                name="get_object_version",
                arguments={"object_version_id": str(uuid4())},
            )
    response = client.get(f"/api/v1/records/{first['object_version_id']}")
    assert response.status_code == (200 if public else 404)
    if public:
        assert response.json()["authorship"]["actor_kind"] == "AGENT"
        assert "PRIVATE CHAT" not in response.text
        assert "run_id" not in response.text


def test_agent_can_write_summary_comment_and_progress_but_not_human_note(
    client: TestClient,
) -> None:
    app, token, run_id, entry, _project = active_run(client, public=True)

    def invoke(name: str, arguments: dict[str, object], ordinal: int) -> dict[str, object]:
        with app.state.session_factory() as db:
            run = db.get(SqlAgentRun, run_id)
            assert run is not None
            invocation = f"activity-{ordinal}"
            append_worker_event(
                db,
                worker_id="direct-test",
                lease_generation=run.lease_generation,
                run_id=run.id,
                kind=AgentRunEventKind.TOOL_REQUESTED,
                idempotency_key=f"{invocation}-requested",
                payload={"tool_name": name},
            )
            cursor = db.scalar(
                select(SqlAgentRunEvent.cursor).where(
                    SqlAgentRunEvent.run_id == run.id,
                    SqlAgentRunEvent.idempotency_key == f"{invocation}-requested",
                )
            )
            assert cursor is not None
            return execute_tool(
                db,
                token=token,
                name=name,
                arguments=arguments,
                idempotency_key=invocation,
                source_event_cursor=cursor,
            )

    summary = invoke(
        "write_summary",
        {
            "object_id": entry["entry_id"],
            "source_object_version_ids": [entry["object_version_id"]],
            "body_md": "Agent-authored source-pinned summary",
        },
        1,
    )
    summary_revision = summary["current_revision"]
    assert isinstance(summary_revision, dict)
    assert summary_revision["actor_kind"] == "AGENT"
    assert summary_revision["source_object_version_ids"] == [entry["object_version_id"]]
    assert "source_revision_ids" not in summary_revision
    assert (
        invoke(
            "write_summary",
            {
                "object_id": entry["entry_id"],
                "source_object_version_ids": [entry["object_version_id"]],
                "body_md": "Agent-authored source-pinned summary",
            },
            1,
        )
        == summary
    )
    with app.state.session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.run_id == run_id)
            )
            == 1
        )
    with pytest.raises(ToolCapabilityInvalid):
        invoke(
            "write_summary",
            {
                "object_id": entry["entry_id"],
                "source_object_version_ids": [entry["object_version_id"]],
                "base_revision_id": summary_revision["id"],
                "body_md": "An ungranted edit",
            },
            4,
        )
    with pytest.raises(ToolCapabilityInvalid):
        invoke(
            "write_summary",
            {
                "object_id": entry["entry_id"],
                "source_revision_ids": [entry["object_version_id"]],
                "body_md": "Old wire",
            },
            1,
        )
    comment = invoke(
        "comment_on_object_version",
        {
            "object_id": entry["entry_id"],
            "object_version_id": entry["object_version_id"],
            "body_md": "Agent comment",
        },
        2,
    )
    assert comment["actor_kind"] == "AGENT"
    progress = invoke(
        "report_progress",
        {
            "object_id": entry["entry_id"],
            "object_version_id": entry["object_version_id"],
            "status": "POTENTIAL",
            "detail_md": "Agent found a possible direction",
        },
        3,
    )
    assert progress["actor_kind"] == "AGENT"

    with app.state.session_factory() as db, pytest.raises(ToolCapabilityInvalid):
        execute_tool(
            db,
            token=token,
            name="write_human_note",
            arguments={},
            idempotency_key="forbidden-note",
            source_event_cursor=1,
        )

    note = client.put(
        f"/api/v1/research/objects/{entry['entry_id']}/human-note",
        headers=headers(key="human-note-remains-human"),
        json={"body_md": "Human-owned"},
    )
    assert note.status_code == 200


def test_outputs_do_not_grant_other_runs_or_later_revision_access(client: TestClient) -> None:
    app, token, run_id, entry, project = active_run(client, public=False)

    def create(capability: str, run: UUID) -> dict[str, object]:
        with app.state.session_factory() as db:
            cursor = db.scalar(
                select(SqlAgentRunEvent.cursor).where(
                    SqlAgentRunEvent.run_id == run,
                    SqlAgentRunEvent.idempotency_key == "direct-1-requested",
                )
            )
            assert cursor is not None
            return execute_tool(
                db,
                token=capability,
                name="write_object_version",
                arguments=attempt_payload(entry["object_version_id"], project_id=project["id"]),
                idempotency_key="direct-1",
                source_event_cursor=cursor,
            )

    first = create(token, run_id)
    _, other_token, other_run, _, _ = active_run(client, public=False, project_id=project["id"])
    other = create(other_token, other_run)
    later_snapshot = attempt_payload(entry["object_version_id"], project_id=project["id"])[
        "snapshot"
    ]
    later_snapshot["content"].update(
        title="Later human version", content_md="Later work", findings_md="New findings"
    )
    revised = post_research(
        client,
        f"/api/v1/objects/{first['id']}/versions",
        headers=headers(),
        json={
            "expected_current_object_version_id": first["object_version_id"],
            "snapshot": later_snapshot,
        },
    )
    assert revised.status_code == 201, revised.text
    with app.state.session_factory() as db:
        own = execute_tool(
            db,
            token=token,
            name="get_object_version",
            arguments={"object_version_id": first["object_version_id"]},
        )
        assert own["id"] == first["object_version_id"]
        for inaccessible in (
            other["object_version_id"],
            revised.json()["current_object_version_id"],
        ):
            with pytest.raises(ToolCapabilityInvalid):
                execute_tool(
                    db,
                    token=token,
                    name="get_object_version",
                    arguments={"object_version_id": inaccessible},
                )
        with pytest.raises(ToolCapabilityInvalid):
            execute_tool(
                db,
                token=other_token,
                name="get_object_version",
                arguments={"object_version_id": first["object_version_id"]},
            )


def test_expiry_at_commit_rolls_back_output_and_can_retry(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, token, run_id, entry, project = active_run(client, public=False)
    payload = attempt_payload(entry["object_version_id"], project_id=project["id"])
    with app.state.session_factory() as db:
        cursor = db.scalar(
            select(SqlAgentRunEvent.cursor).where(
                SqlAgentRunEvent.run_id == run_id,
                SqlAgentRunEvent.idempotency_key == "direct-1-requested",
            )
        )
        assert cursor is not None

        def write() -> dict[str, object]:
            return execute_tool(
                db,
                token=token,
                name="write_object_version",
                arguments=payload,
                idempotency_key="direct-1",
                source_event_cursor=cursor,
            )

        with monkeypatch.context() as clock:
            clock.setattr(direct_contributions, "utc_now", lambda: utc_now() + timedelta(minutes=5))
            with pytest.raises(ToolCapabilityInvalid):
                write()
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlRunRevisionOutput)
                .where(SqlRunRevisionOutput.run_id == run_id)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(SqlContributionEnvelope)
                .where(SqlContributionEnvelope.run_id == run_id)
            )
            == 0
        )
        assert write()["object_version_id"]

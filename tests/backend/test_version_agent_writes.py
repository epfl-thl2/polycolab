"""Current tool contracts retain the existing lease/grant/retry enforcement."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_direct_contributions import active_run
from test_version_api import snapshot

from polycolab.agents.tools import ToolCapabilityInvalid, execute_tool
from polycolab.db.models import SqlAgentRunEvent


@pytest.mark.parametrize(
    "tool,operation",
    [("comment_on_object_version", "COMMENT"), ("report_progress", "REPORT_PROGRESS")],
)
def test_agent_activity_uses_object_version_contract_and_preserves_retry(
    client: TestClient, tool: str, operation: str
) -> None:
    app, token, run_id, entry, _ = active_run(
        client,
        public=True,
        allowed_operations=[operation],
        requested_tool_name=tool,
    )
    payload: dict[str, object] = {
        "object_id": entry["entry_id"],
        "object_version_id": entry["object_version_id"],
        "project_id": None,
        **(
            {"body_md": "Review this exact formulation"}
            if operation == "COMMENT"
            else {"status": "PARTIAL", "detail_md": "A case remains"}
        ),
    }
    with app.state.session_factory() as session:
        cursor = session.scalar(
            select(SqlAgentRunEvent.cursor).where(
                SqlAgentRunEvent.run_id == run_id,
                SqlAgentRunEvent.idempotency_key == "direct-1-requested",
            )
        )
        assert cursor is not None

        def invoke(name: str, arguments: dict[str, object]) -> dict[str, object]:
            return execute_tool(
                session,
                token=token,
                name=name,
                arguments=arguments,
                idempotency_key="direct-1",
                source_event_cursor=cursor,
            )

        saved = invoke(tool, payload)
        assert saved["object_version_id"] == entry["object_version_id"]
        assert "revision_id" not in saved
        assert invoke(tool, payload) == saved
        with pytest.raises(ToolCapabilityInvalid):
            invoke("comment_on_revision", payload)
        with pytest.raises(ToolCapabilityInvalid):
            invoke(
                tool,
                {
                    **{key: value for key, value in payload.items() if key != "object_version_id"},
                    "revision_id": entry["object_version_id"],
                },
            )


@pytest.mark.parametrize("public", [False, True])
def test_agent_complete_snapshot_retry_and_exact_read(client: TestClient, public: bool) -> None:
    app, token, run_id, entry, project = active_run(client, public=public)
    value = snapshot()
    value["kind"] = "NOTE"
    value["content"].pop("statement_label", None)
    value["structural_relationships"] = [
        {
            "relationship_type": "ATTACHMENT",
            "target_object_version_id": entry["object_version_id"],
        }
    ]
    payload: dict[str, object] = {
        "destination": {
            "kind": "library",
            "statement_object_version_id": entry["object_version_id"],
        }
        if public
        else {"kind": "project", "project_id": project["id"]},
        "snapshot": value,
    }
    with app.state.session_factory() as session:
        cursor = session.scalar(
            select(SqlAgentRunEvent.cursor).where(
                SqlAgentRunEvent.run_id == run_id,
                SqlAgentRunEvent.idempotency_key == "direct-1-requested",
            )
        )
        assert cursor is not None

        def write() -> dict[str, object]:
            return execute_tool(
                session,
                token=token,
                name="write_object_version",
                arguments=payload,
                idempotency_key="direct-1",
                source_event_cursor=cursor,
            )

        saved = write()
        assert write() == saved
        assert "revision_id" not in saved
        read = execute_tool(
            session,
            token=token,
            name="get_object_version",
            arguments={"object_version_id": saved["object_version_id"]},
        )
        assert read["content"] == {**value["content"], "attached_object_ids": [entry["entry_id"]]}
        assert read["change_summary"] is None
        assert read["omitted_structural_relationship_count"] == 0
        assert isinstance(read["authorship"], dict)
        assert read["authorship"]["actor_kind"] == "AGENT"
        with pytest.raises(ToolCapabilityInvalid):
            execute_tool(
                session,
                token=token,
                name="write_record",
                arguments=payload,
                idempotency_key="old-name",
                source_event_cursor=cursor,
            )

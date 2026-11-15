"""Populated transcript cutover preserves causality, identity, and replay history."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, insert, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from polycolab.db.models import (
    SqlAgentRunEvent,
    SqlArtifact,
    SqlContextManifest,
    SqlContextManifestArtifact,
    SqlPlatformAgentVersion,
    SqlProject,
    SqlProjectRepository,
    SqlUser,
)
from polycolab.entities.time import utc_now
from polycolab.operations.local_development import MIGRATIONS, upgrade_database


def populate(connection: Connection) -> dict[str, UUID]:
    ids = {
        key: uuid4()
        for key in (
            "user",
            "project",
            "agent",
            "profile",
            "session",
            "request",
            "second_request",
            "answer",
            "run",
            "second_run",
            "call",
            "result",
            "complete",
            "failure",
            "binding",
            "task",
            "scope",
            "manifest",
            "grant",
            "proposal",
            "contribution",
            "artifact",
            "exact_version",
        )
    }
    now = utc_now()
    connection.execute(insert(SqlUser).values(id=ids["user"], issuer="migration", subject="owner"))
    connection.execute(
        insert(SqlProject).values(
            id=ids["project"],
            name="History",
            created_by_user_id=ids["user"],
            visibility="PRIVATE",
        )
    )
    connection.execute(
        insert(SqlPlatformAgentVersion).values(
            id=ids["agent"],
            agent_kind="RESEARCHER",
            version=9001,
            display_name="Researcher",
            instructions_text="Private",
            instructions_digest="a" * 64,
        )
    )

    def old(name: str) -> Table:
        return Table(name, MetaData(), autoload_with=connection)

    def key(name: str) -> str | UUID:
        return ids[name].hex if connection.dialect.name == "sqlite" else ids[name]

    connection.execute(
        old("gateway_profiles")
        .insert()
        .values(
            id=key("profile"),
            user_id=key("user"),
            display_name="Provider",
            base_url="https://example.test",
            model_id="model",
            wire_api="responses",
            credential_version=1,
            encrypted_credential=b"test",
            wrapped_data_key=b"test",
            encryption_key_version="test",
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(old("project_tasks")).values(
            id=key("task"),
            project_id=key("project"),
            title="Saved worktree",
            branch="tasks/history",
            created_at=now,
            updated_at=now,
            created_by_user_id=key("user"),
        )
    )
    connection.execute(
        old("agent_sessions")
        .insert()
        .values(
            id=key("session"),
            project_id=key("project"),
            agent_version_id=key("agent"),
            created_by_user_id=key("user"),
            is_shared=True,
            status="ACTIVE",
            title="Preserve me",
            task_id=key("task"),
            harness="codex",
            system_prompt="Private preserved prompt",
            next_message_sequence=3,
            next_run_sequence=2,
            created_at=now,
            updated_at=now,
        )
    )
    for sequence, name, role, content in (
        (1, "request", "USER", "First **request**"),
        (2, "second_request", "USER", "Queued while the first run executes"),
        (3, "answer", "AGENT", "Saved answer"),
    ):
        connection.execute(
            old("agent_messages")
            .insert()
            .values(
                id=key(name),
                session_id=key("session"),
                sequence=sequence,
                role=role,
                author_user_id=key("user") if role == "USER" else None,
                content_md=content,
                created_at=now + timedelta(seconds=sequence),
            )
        )
    for sequence, run, message in (
        (1, "run", "request"),
        (2, "second_run", "second_request"),
    ):
        connection.execute(
            old("agent_runs")
            .insert()
            .values(
                id=key(run),
                session_id=key("session"),
                project_id=key("project"),
                agent_version_id=key("agent"),
                requested_by_user_id=key("user"),
                request_message_id=key(message),
                gateway_profile_id=key("profile"),
                gateway_credential_version=1,
                gateway_model_id="model",
                queue_sequence=sequence,
                input_message_sequence=sequence,
                status="COMPLETED" if sequence == 1 else "FAILED",
                next_event_cursor=3 if sequence == 1 else 1,
                requested_context_artifact_ids=[str(ids["artifact"])],
                client_request_id=key(run),
                attempt=0,
                lease_generation=0,
                created_at=now,
                updated_at=now,
            )
        )
    for cursor, name, run, kind, payload in (
        (1, "call", "run", "TOOL_REQUESTED", {"tool_name": "search", "round": 1}),
        (
            2,
            "result",
            "run",
            "TOOL_RESULT",
            {"tool_name": "search", "round": 1, "outcome": "ok"},
        ),
        (
            3,
            "complete",
            "run",
            "ASSISTANT_MESSAGE_COMPLETED",
            {"message_id": str(ids["answer"]), "sequence": 3},
        ),
        (1, "failure", "second_run", "RUN_FAILED", {"code": "runner_lost"}),
    ):
        connection.execute(
            insert(SqlAgentRunEvent).values(
                id=ids[name],
                run_id=ids[run],
                cursor=cursor,
                idempotency_key=name,
                kind=kind,
                payload=payload,
                # Deliberately backwards timestamps: causality must dominate them.
                occurred_at=now - timedelta(seconds=cursor),
            )
        )
    connection.execute(
        old("runtime_session_bindings")
        .insert()
        .values(
            id=key("binding"),
            session_id=key("session"),
            adapter_name="codex",
            opaque_runtime_ref="private-external-session",
            status="ACTIVE",
            created_at=now,
        )
    )
    connection.execute(insert(SqlProjectRepository).values(project_id=ids["project"]))
    connection.execute(
        old("repository_sessions")
        .insert()
        .values(session_id=key("session"), project_id=key("project"), base_commit="a" * 40)
    )
    connection.execute(
        old("repository_runs")
        .insert()
        .values(
            run_id=key("run"),
            session_id=key("session"),
            input_commit="a" * 40,
            output_commit="b" * 40,
            worktree_id=key("task"),
        )
    )

    connection.execute(
        insert(SqlContextManifest).values(
            id=ids["manifest"],
            run_id=ids["run"],
            project_id=ids["project"],
            requested_by_user_id=ids["user"],
            agent_version_id=ids["agent"],
            artifact_ids=[str(ids["artifact"])],
            digest="c" * 64,
        )
    )

    connection.execute(
        old("run_tool_capabilities")
        .insert()
        .values(
            id=key("grant"),
            token_digest="e" * 64,
            run_id=key("run"),
            session_id=key("session"),
            project_id=key("project"),
            user_id=key("user"),
            agent_version_id=key("agent"),
            context_manifest_id=key("manifest"),
            allowed_tools=["get_context"],
            revoked=False,
            created_at=now,
            lease_generation=1,
            expires_at=now + timedelta(hours=1),
        )
    )

    connection.execute(
        insert(SqlArtifact).values(
            id=ids["artifact"],
            project_id=ids["project"],
            created_by_user_id=ids["user"],
            sha256="f" * 64,
            byte_length=5,
            media_type="text/plain",
            storage_key="preserved/artifact",
            state="COMMITTED",
            expires_at=now + timedelta(hours=1),
            verified_at=now,
            committed_at=now,
        )
    )
    connection.execute(
        insert(SqlContextManifestArtifact).values(
            manifest_id=ids["manifest"], artifact_id=ids["artifact"], position=0
        )
    )
    for name in ("direct", "standalone", "completed", "failed", "pending"):
        ids[name] = uuid4()
    for name in ("direct", "standalone"):
        connection.execute(
            old("chat_conversations")
            .insert()
            .values(
                id=key(name),
                user_id=key("user"),
                project_id=key("project") if name == "direct" else None,
                title=name,
                sequence=2 if name == "direct" else 1,
                created_at=now,
                updated_at=now,
            )
        )
    for sequence, name, parent, response, failure in (
        (1, "completed", "direct", "Preserved direct reply", None),
        (2, "failed", "direct", None, "provider_unavailable"),
        (1, "pending", "standalone", None, None),
    ):
        connection.execute(
            old("chat_turns")
            .insert()
            .values(
                id=key(name),
                conversation_id=key(parent),
                request_id=key(name),
                sequence=sequence,
                profile_id=key("profile"),
                model_id="selected-direct-model",
                content_md=name + " request",
                response_md=response,
                status=name,
                failure_code=failure,
                reserved_tokens=1000,
                reserved_cost_microusd=2000,
                input_tokens=12 if name == "completed" else None,
                output_tokens=18 if name == "completed" else None,
                created_at=now,
            )
        )
    return ids


def verify(connection: Connection, ids: dict[str, UUID]) -> None:
    def table(name: str) -> Table:
        return Table(name, MetaData(), autoload_with=connection)

    rows = list(
        connection.execute(select(table("conversation_items")).order_by("sequence")).mappings()
    )
    rows = [row for row in rows if UUID(str(row["conversation_id"])) == ids["session"]]
    by_id = {UUID(str(row["id"])): row for row in rows}
    assert len(rows) == 6
    assert [row["sequence"] for row in rows] == list(range(1, 7))
    assert by_id[ids["request"]]["content_md"] == "First **request**"
    assert by_id[ids["answer"]]["content_md"] == "Saved answer"
    assert (
        by_id[ids["request"]]["sequence"]
        < by_id[ids["second_request"]]["sequence"]
        < by_id[ids["answer"]]["sequence"]
    )
    call, result, failure = (
        by_id[uuid5(ids[name], "conversation-item")] for name in ("call", "result", "failure")
    )
    assert (
        by_id[ids["request"]]["sequence"]
        < call["sequence"]
        < result["sequence"]
        < by_id[ids["answer"]]["sequence"]
    )
    assert by_id[ids["second_request"]]["sequence"] < failure["sequence"]
    assert call["payload"]["arguments_json"] is None
    assert result["payload"]["output_json"] is None
    assert call["payload"]["call_id"] is None
    assert failure["payload"] == {"code": "runner_lost"}
    assert UUID(str(by_id[ids["answer"]]["agent_version_id"])) == ids["agent"]
    for run in connection.execute(select(table("agent_runs"))).mappings():
        message = by_id[UUID(str(run["request_message_id"]))]
        assert run["input_message_sequence"] == message["sequence"]
        assert UUID(str(message["execution_id"])) == UUID(str(run["id"]))
        assert run["requested_context_artifact_ids"] == [str(ids["artifact"])]
    inspector = inspect(connection)
    for name in inspector.get_table_names():
        assert all(
            foreign_key["referred_table"]
            not in {
                "agent_sessions",
                "agent_messages",
                "chat_conversations",
                "chat_turns",
            }
            for foreign_key in inspector.get_foreign_keys(name)
        )
    for name in (
        "repository_conversations",
        "repository_runs",
        "run_tool_capabilities",
    ):
        dependent = connection.execute(select(table(name))).mappings().one()
        assert UUID(str(dependent["conversation_id"])) == ids["session"]
    manifest = connection.execute(select(table("context_manifests"))).mappings().one()
    assert manifest["artifact_ids"] == [str(ids["artifact"])]
    output = connection.execute(select(table("artifacts"))).mappings().one()
    assert UUID(str(output["project_id"])) == ids["project"]
    assert output["sha256"] == "f" * 64 and output["storage_key"] == "preserved/artifact"
    member = connection.execute(select(table("context_manifest_artifacts"))).mappings().one()
    assert UUID(str(member["artifact_id"])) == ids["artifact"]
    assert UUID(str(member["manifest_id"])) == ids["manifest"]
    repository = connection.execute(select(table("repository_runs"))).mappings().one()
    assert UUID(str(repository["worktree_id"])) == ids["task"]
    assert repository["input_commit"] == "a" * 40 and repository["output_commit"] == "b" * 40
    binding = connection.execute(select(table("runtime_session_bindings"))).mappings().one()
    assert UUID(str(binding["conversation_id"])) == ids["session"]
    assert binding["opaque_runtime_ref"] == "private-external-session"
    conversation = next(
        row
        for row in connection.execute(select(table("conversations"))).mappings()
        if row["origin"] == "agent"
    )
    assert UUID(str(conversation["root_id"])) == ids["session"]
    assert UUID(str(conversation["worktree_id"])) == ids["task"]
    assert conversation["sharing"] == "members_can_view"
    assert conversation["next_message_sequence"] == 6
    configuration = (
        connection.execute(select(table("conversation_configurations"))).mappings().one()
    )
    assert UUID(str(configuration["conversation_id"])) == ids["session"]
    assert UUID(str(configuration["agent_version_id"])) == ids["agent"]
    assert configuration["agent_display_name"] == "Researcher"
    assert configuration["harness"] == "codex"
    assert configuration["system_prompt"] == "Private preserved prompt"
    assert configuration["harness_version"] is None
    assert configuration["connection_protocol"] is None
    legacy = list(connection.execute(select(table("legacy_conversation_executions"))).mappings())
    assert len(legacy) == 3
    by_execution = {UUID(str(row["id"])): row for row in legacy}
    for name in ("completed", "failed", "pending"):
        execution = by_execution[ids[name]]
        assert UUID(str(execution["request_id"])) == ids[name]
        assert execution["reserved_tokens"] == 1000
        assert execution["reserved_cost_microusd"] == 2000
        assert execution["model_id"] == "selected-direct-model"
    assert by_execution[ids["pending"]]["status"] == "interrupted"
    assert by_execution[ids["pending"]]["failure_code"] == "chat_request_interrupted"
    assert by_execution[ids["failed"]]["failure_code"] == "provider_unavailable"
    assert by_execution[ids["failed"]]["input_tokens"] is None
    assert by_execution[ids["completed"]]["input_tokens"] == 12
    assert by_execution[ids["completed"]]["output_tokens"] == 18
    all_items = {
        UUID(str(row["id"])): row
        for row in connection.execute(select(table("conversation_items"))).mappings()
    }
    assert (
        all_items[uuid5(ids["completed"], "conversation-assistant")]["content_md"]
        == "Preserved direct reply"
    )
    assert all_items[uuid5(ids["pending"], "conversation-human")]["status"] == "interrupted"
    standalone = next(
        row
        for row in connection.execute(select(table("conversations"))).mappings()
        if UUID(str(row["id"])) == ids["standalone"]
    )
    assert standalone["project_id"] is None
    assert standalone["origin"] == "legacy_direct"
    assert standalone["sharing"] == "private"
    assert "chat_conversations" not in inspect(connection).get_table_names()
    assert "chat_turns" not in inspect(connection).get_table_names()
    from polycolab.db.stores.conversations import SqlConversationStore
    from polycolab.entities.enums import UsageSource

    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        store = SqlConversationStore(session)
        snapshot = store.conversation(ids["direct"])
        assert snapshot is not None and snapshot.configuration is None
        assert snapshot.title == "direct"
        executions = store.legacy_runs(ids["direct"])
        transcript = store.items(ids["direct"])
        records = store.executions(ids["direct"])
        interrupted = store.execution(ids["pending"])
        latest = store.latest_executions([ids["direct"], ids["standalone"]])
    assert executions[0].usage.reservations[0].tokens == 1000
    assert executions[0].usage.observations[0].source is UsageSource.PROVIDER_REPORTED
    assert executions[0].usage.observations[0].input_tokens == 12
    assert executions[1].usage.observations[0].source is UsageSource.UNKNOWN
    assert executions[1].usage.observations[0].total_tokens is None
    assert [item.type for item in transcript] == [
        "message",
        "message",
        "message",
        "error",
    ]
    assert [record.id for record in records] == [execution.id for execution in executions]
    assert records[0].summary.observed_model is None
    assert records[0].context is None
    assert records[0].request_item_id == uuid5(records[0].id, "conversation-human")
    assert interrupted is not None and interrupted.summary.status == "INTERRUPTED"
    assert interrupted.summary.started_at is None and interrupted.summary.finished_at is None
    assert interrupted.attempt is None and interrupted.updated_at is None
    assert latest[ids["direct"]].id == records[-1].id

    for name, values in (
        (
            "conversation_configurations",
            {"system_prompt": "Cannot replace pinned prompt"},
        ),
        ("legacy_conversation_executions", {"model_id": "Cannot rewrite accounting"}),
    ):
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(table(name).update().values(**values))

    events = list(connection.execute(select(table("agent_run_events"))).mappings())
    assert {UUID(str(event["id"])) for event in events} == {
        ids[name] for name in ("call", "result", "complete", "failure")
    }
    completion = next(event for event in events if UUID(str(event["id"])) == ids["complete"])
    assert completion["cursor"] == 3
    assert completion["payload"] == {"message_id": str(ids["answer"]), "sequence": 3}


def test_sqlite_populated_conversation_cutover(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    engine = create_engine(f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "local_20261029_workspace_only")
        ids = populate(connection)
    upgrade_database(path)
    with engine.connect() as connection:
        verify(connection, ids)
        assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    assert upgrade_database(path) is None
    engine.dispose()


def test_postgresql_populated_conversation_cutover(
    pg_schema: tuple[Engine, Config, str],
) -> None:
    engine, config, _ = pg_schema
    command.upgrade(config, "20261029_workspace_only")
    with engine.begin() as connection:
        ids = populate(connection)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        verify(connection, ids)

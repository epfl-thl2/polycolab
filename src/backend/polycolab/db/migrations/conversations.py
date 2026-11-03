"""Frozen canonical transcript cutover shared by PostgreSQL and SQLite."""

from collections import defaultdict
from heapq import heappop, heappush
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import context, op


def upgrade() -> None:
    op.rename_table("agent_sessions", "conversations")
    op.rename_table("agent_messages", "conversation_items")
    for table, old, columns in (
        (
            "conversations",
            "agent_sessions",
            ("agent_version_id", "created_by_user_id", "project_id", "task_id"),
        ),
        ("conversation_items", "agent_messages", ("session_id",)),
    ):
        for column in columns:
            op.drop_index(f"ix_{old}_{column}", table_name=table)
            op.create_index(f"ix_{table}_{column}", table, [column])
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("project_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("agent_version_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("origin", sa.String(24), nullable=False, server_default="agent"))
        batch.add_column(
            sa.Column("sharing", sa.String(24), nullable=False, server_default="private")
        )
        batch.add_column(sa.Column("root_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("spawning_run_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("spawning_item_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("delegated_task", sa.Text(), nullable=True))
        batch.create_foreign_key("fk_conversations_root_id", "conversations", ["root_id"], ["id"])
        batch.create_foreign_key(
            "fk_conversations_parent_id", "conversations", ["parent_id"], ["id"]
        )
        batch.create_check_constraint(
            "ck_conversations_origin", "origin IN ('agent', 'legacy_direct')"
        )
        batch.create_check_constraint(
            "ck_conversations_sharing",
            "sharing IN ('private', 'project_readable', 'project_contributable')",
        )
    op.execute(
        "UPDATE conversations SET root_id = id, sharing = CASE WHEN is_shared "
        "THEN 'project_readable' ELSE 'private' END"
    )
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column("root_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("is_shared")
        batch.create_check_constraint(
            "ck_conversations_hierarchy",
            "(parent_id IS NULL AND root_id = id) OR "
            "(parent_id IS NOT NULL AND parent_id != id AND root_id != id)",
        )
    with op.batch_alter_table("conversation_items") as batch:
        batch.add_column(sa.Column("agent_version_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("execution_id", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column("item_type", sa.String(16), nullable=False, server_default="message")
        )
        batch.add_column(
            sa.Column("status", sa.String(16), nullable=False, server_default="completed")
        )
        batch.add_column(
            sa.Column("visibility", sa.String(16), nullable=False, server_default="user_visible")
        )
        batch.add_column(sa.Column("payload", sa.JSON(), nullable=True))
        batch.create_foreign_key(
            "fk_conversation_items_agent_version_id",
            "platform_agent_versions",
            ["agent_version_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_conversation_items_type",
            "item_type IN ('message', 'tool_call', 'tool_result', 'error')",
        )
        batch.create_check_constraint(
            "ck_conversation_items_status", "status IN ('completed', 'interrupted', 'in_progress')"
        )
        batch.create_check_constraint(
            "ck_conversation_items_visibility", "visibility IN ('user_visible', 'model_only')"
        )
    # Data migrations require an actual database. Offline scripts are schema
    # inspection only; release upgrades must run online with writers stopped.
    if context.is_offline_mode():
        op.execute("-- Transcript data backfill requires an online Alembic upgrade")
        return
    connection = op.get_bind()
    postgres = connection.dialect.name == "postgresql"
    if postgres:
        op.execute("ALTER TABLE conversation_items DISABLE TRIGGER agent_messages_immutable")
    _backfill(connection)
    _configuration(connection)
    _legacy(connection)
    if postgres:
        op.execute("ALTER TABLE conversation_items ENABLE TRIGGER agent_messages_immutable")


def _key(value: object) -> str:
    return str(UUID(str(value)))


def _backfill(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    tables = {
        name: sa.Table(name, metadata, autoload_with=connection)
        for name in ("conversations", "conversation_items", "agent_runs", "agent_run_events")
    }
    conversations, items, runs, events = (tables[name] for name in tables)
    for conversation in connection.execute(sa.select(conversations)).mappings():
        messages = [
            dict(row)
            for row in connection.execute(
                sa.select(items)
                .where(items.c.session_id == conversation["id"])
                .order_by(items.c.sequence)
            ).mappings()
        ]
        executions = [
            dict(row)
            for row in connection.execute(
                sa.select(runs).where(runs.c.session_id == conversation["id"])
            ).mappings()
        ]
        if not messages and not executions:
            continue
        nodes: dict[str, dict] = {}
        edges: dict[str, set[str]] = defaultdict(set)
        incoming: dict[str, int] = defaultdict(int)
        old_sequences = {row["sequence"]: _key(row["id"]) for row in messages}

        def link(before: str, after: str, edges: dict = edges, incoming: dict = incoming) -> None:
            if before != after and after not in edges[before]:
                edges[before].add(after)
                incoming[after] += 1

        previous = None
        for message in messages:
            key = _key(message["id"])
            nodes[key] = {"time": str(message["created_at"]), "item": message}
            if message["role"] == "AGENT":
                message["agent_version_id"] = conversation["agent_version_id"]
            if previous is not None:
                link(previous, key)
            previous = key
        for run in executions:
            stream = list(
                connection.execute(
                    sa.select(events).where(events.c.run_id == run["id"]).order_by(events.c.cursor)
                ).mappings()
            )
            previous = old_sequences.get(run["input_message_sequence"])
            if run["request_message_id"] is not None:
                request_key = _key(run["request_message_id"])
                nodes[request_key]["item"]["execution_id"] = run["id"]
            for event in stream:
                payload = event["payload"]
                key = "event:" + _key(event["id"])
                if event["kind"] == "ASSISTANT_MESSAGE_COMPLETED":
                    key = _key(payload["message_id"])
                    if key not in nodes:
                        raise RuntimeError("completion references a missing conversation item")
                    nodes[key]["item"]["execution_id"] = run["id"]
                else:
                    nodes[key] = {"time": str(event["occurred_at"]), "item": None}
                    semantic = _semantic(event)
                    if semantic is not None:
                        item_type, data, role = semantic
                        identity = uuid5(UUID(_key(event["id"])), "conversation-item")
                        nodes[key]["item"] = {
                            "id": identity
                            if connection.dialect.name == "postgresql"
                            else identity.hex,
                            "session_id": conversation["id"],
                            "sequence": 0,
                            "role": role,
                            "author_user_id": None,
                            "agent_version_id": run["agent_version_id"],
                            "execution_id": run["id"],
                            "item_type": item_type,
                            "payload": data,
                            "content_md": "",
                            "status": "completed",
                            "visibility": "user_visible",
                            "created_at": event["occurred_at"],
                        }
                if previous is not None:
                    link(previous, key)
                previous = key
        ready = [(node["time"], key) for key, node in nodes.items() if not incoming[key]]
        from heapq import heapify

        heapify(ready)
        ordered = []
        visited = 0
        while ready:
            _, key = heappop(ready)
            visited += 1
            if nodes[key]["item"] is not None:
                ordered.append((key, nodes[key]["item"]))
            for child in edges[key]:
                incoming[child] -= 1
                if incoming[child] == 0:
                    heappush(ready, (nodes[child]["time"], child))
        if visited != len(nodes):
            raise RuntimeError("conversation history has inconsistent causal ordering")
        # Free the unique sequence slots while retaining positive-sequence checks.
        shift = max(old_sequences, default=0) + len(ordered) + 1
        connection.execute(
            items.update()
            .where(items.c.session_id == conversation["id"])
            .values(sequence=items.c.sequence + shift)
        )
        new_sequences = {}
        for sequence, (key, item) in enumerate(ordered, 1):
            item["sequence"] = sequence
            new_sequences[key] = sequence
            if key.startswith("event:"):
                connection.execute(items.insert().values(**item))
            else:
                connection.execute(items.update().where(items.c.id == item["id"]).values(**item))
        for run in executions:
            old_frontier = old_sequences.get(run["input_message_sequence"])
            if old_frontier is None:
                raise RuntimeError("run input references a missing conversation sequence")
            connection.execute(
                runs.update()
                .where(runs.c.id == run["id"])
                .values(input_message_sequence=new_sequences[old_frontier])
            )
        connection.execute(
            conversations.update()
            .where(conversations.c.id == conversation["id"])
            .values(next_message_sequence=len(ordered))
        )
        persisted = list(
            connection.execute(
                sa.select(items)
                .where(items.c.session_id == conversation["id"])
                .order_by(items.c.sequence)
            ).mappings()
        )
        if len(persisted) != len(ordered):
            raise RuntimeError("conversation item count mismatch")
        for row, (_, expected) in zip(persisted, ordered, strict=True):
            if any(row[name] != value for name, value in expected.items()):
                raise RuntimeError("conversation item verification failed")


def _semantic(event: sa.RowMapping) -> tuple[str, dict, str] | None:
    payload = event["payload"]
    kind = event["kind"]
    if kind in {"TOOL_REQUESTED", "TOOL_RESULT"}:
        # Historic streams did not store provider call IDs or argument bodies.
        # The event identity is an invocation reference, not a fabricated provider ID.
        data = {"call_id": None, "name": payload["tool_name"], "event_id": _key(event["id"])}
        if kind == "TOOL_REQUESTED":
            return "tool_call", {**data, "arguments_json": None}, "AGENT"
        return (
            "tool_result",
            {**data, "outcome": payload.get("outcome", "unknown"), "output_json": None},
            "SYSTEM",
        )
    if kind in {"RUN_FAILED", "RUN_TIMED_OUT", "RUN_CANCELLED"}:
        return "error", {"code": payload.get("code") or kind.lower()}, "SYSTEM"
    return None


def _configuration(connection: sa.Connection) -> None:
    op.create_table(
        "conversation_configurations",
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), primary_key=True
        ),
        sa.Column(
            "agent_version_id",
            sa.Uuid(),
            sa.ForeignKey("platform_agent_versions.id"),
            nullable=False,
        ),
        sa.Column("agent_display_name", sa.String(200), nullable=False),
        sa.Column("agent_kind", sa.String(32), nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column("harness", sa.String(100), nullable=False),
        sa.Column("harness_version", sa.String(100)),
        sa.Column("connection_protocol", sa.String(100)),
        sa.Column("system_prompt", sa.Text()),
    )
    op.create_index(
        "ix_conversation_configurations_agent_version_id",
        "conversation_configurations",
        ["agent_version_id"],
    )
    op.execute("""INSERT INTO conversation_configurations
        (conversation_id, agent_version_id, agent_display_name, agent_kind,
         agent_version, harness, system_prompt)
        SELECT c.id, a.id, a.display_name, a.agent_kind, a.version,
               COALESCE(c.harness, 'platform'), c.system_prompt
        FROM conversations c JOIN platform_agent_versions a ON c.agent_version_id = a.id""")
    count = connection.scalar(sa.text("SELECT count(*) FROM conversations"))
    copied = connection.scalar(sa.text("SELECT count(*) FROM conversation_configurations"))
    if copied != count:
        raise RuntimeError("conversation configuration backfill is incomplete")
    op.drop_index("ix_conversations_agent_version_id", table_name="conversations")
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    foreign = next(
        fk
        for fk in sa.inspect(connection).get_foreign_keys("conversations")
        if fk["constrained_columns"] == ["agent_version_id"]
    )
    with op.batch_alter_table("conversations", naming_convention=naming) as batch:
        batch.drop_constraint(
            foreign["name"] or "fk_conversations_agent_version_id_platform_agent_versions",
            type_="foreignkey",
        )
        batch.drop_constraint("ck_agent_sessions_custom_configuration", type_="check")
        batch.drop_column("agent_version_id")
        batch.drop_column("harness")
        batch.drop_column("system_prompt")
    if connection.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER conversation_configurations_immutable BEFORE UPDATE OR DELETE "
            "ON conversation_configurations FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    else:
        op.execute(
            "CREATE TRIGGER conversation_configurations_immutable_update "
            "BEFORE UPDATE ON conversation_configurations "
            "BEGIN SELECT RAISE(ABORT, 'immutable configuration'); END"
        )
        op.execute(
            "CREATE TRIGGER conversation_configurations_immutable_delete "
            "BEFORE DELETE ON conversation_configurations "
            "BEGIN SELECT RAISE(ABORT, 'immutable configuration'); END"
        )


def _legacy(connection: sa.Connection) -> None:
    op.create_table(
        "legacy_conversation_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("gateway_profiles.id"), nullable=False),
        sa.Column("model_id", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(100)),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_legacy_execution_request"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_legacy_execution_sequence"),
        sa.CheckConstraint(
            "status IN ('completed', 'failed', 'interrupted')", name="ck_legacy_execution_status"
        ),
    )
    op.create_index(
        "ix_legacy_conversation_executions_conversation_id",
        "legacy_conversation_executions",
        ["conversation_id"],
    )
    metadata = sa.MetaData()
    old_conversations, old_turns, conversations, items, executions = (
        sa.Table(name, metadata, autoload_with=connection)
        for name in (
            "chat_conversations",
            "chat_turns",
            "conversations",
            "conversation_items",
            "legacy_conversation_executions",
        )
    )
    source_count = connection.scalar(sa.select(sa.func.count()).select_from(old_turns))
    copied = 0
    for old in connection.execute(sa.select(old_conversations)).mappings():
        connection.execute(
            conversations.insert().values(
                id=old["id"],
                created_by_user_id=old["user_id"],
                project_id=old["project_id"],
                title=old["title"],
                created_at=old["created_at"],
                updated_at=old["updated_at"],
                origin="legacy_direct",
                sharing="private",
                root_id=old["id"],
                status="ACTIVE",
                next_message_sequence=0,
                next_run_sequence=0,
            )
        )
        sequence = 0
        turn_count = 0
        for turn in connection.execute(
            sa.select(old_turns)
            .where(old_turns.c.conversation_id == old["id"])
            .order_by(old_turns.c.sequence)
        ).mappings():
            # Execution IDs are globally distinguishable from existing agent runs.
            if connection.scalar(
                sa.text("SELECT count(*) FROM agent_runs WHERE id=:id").bindparams(id=turn["id"])
            ):
                raise RuntimeError("legacy execution identity collides with an agent run")
            execution = {name: turn[name] for name in executions.c.keys()}
            if turn["status"] == "pending":
                execution["status"] = "interrupted"
                execution["failure_code"] = turn["failure_code"] or "chat_request_interrupted"
            connection.execute(executions.insert().values(**execution))
            saved = (
                connection.execute(sa.select(executions).where(executions.c.id == turn["id"]))
                .mappings()
                .one()
            )
            if dict(saved) != execution:
                raise RuntimeError("legacy execution accounting verification failed")
            content = [("human", "USER", turn["content_md"], None)]
            if turn["response_md"] is not None:
                content.append(("assistant", "AGENT", turn["response_md"], None))
            if execution["failure_code"] is not None:
                content.append(("error", "SYSTEM", "", {"code": execution["failure_code"]}))
            for suffix, role, text, payload in content:
                sequence += 1
                identity = uuid5(UUID(_key(turn["id"])), "conversation-" + suffix)
                record = {
                    "id": identity if connection.dialect.name == "postgresql" else identity.hex,
                    "session_id": old["id"],
                    "sequence": sequence,
                    "role": role,
                    "author_user_id": old["user_id"] if role == "USER" else None,
                    "agent_version_id": None,
                    "execution_id": turn["id"],
                    "content_md": text,
                    "item_type": "error" if suffix == "error" else "message",
                    "payload": payload,
                    "status": "interrupted"
                    if execution["status"] == "interrupted"
                    else "completed",
                    "visibility": "user_visible",
                    "created_at": turn["created_at"],
                }
                connection.execute(items.insert().values(**record))
                saved_item = (
                    connection.execute(sa.select(items).where(items.c.id == record["id"]))
                    .mappings()
                    .one()
                )
                if any(saved_item[name] != value for name, value in record.items()):
                    raise RuntimeError("legacy transcript verification failed")
            copied += 1
            turn_count += 1
        connection.execute(
            conversations.update()
            .where(conversations.c.id == old["id"])
            .values(next_message_sequence=sequence, next_run_sequence=turn_count)
        )
    if copied != source_count:
        raise RuntimeError("legacy execution count mismatch")
    op.drop_table("chat_turns")
    op.drop_table("chat_conversations")
    if connection.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER legacy_conversation_executions_immutable BEFORE UPDATE OR DELETE "
            "ON legacy_conversation_executions FOR EACH ROW "
            "EXECUTE FUNCTION forbid_history_mutation()"
        )
    else:
        op.execute(
            "CREATE TRIGGER legacy_conversation_executions_immutable_update "
            "BEFORE UPDATE ON legacy_conversation_executions "
            "BEGIN SELECT RAISE(ABORT, 'immutable execution'); END"
        )
        op.execute(
            "CREATE TRIGGER legacy_conversation_executions_immutable_delete "
            "BEFORE DELETE ON legacy_conversation_executions "
            "BEGIN SELECT RAISE(ABORT, 'immutable execution'); END"
        )

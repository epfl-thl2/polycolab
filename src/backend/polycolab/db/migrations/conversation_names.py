"""Frozen conversation vocabulary cutover shared by both database histories."""

import re

import sqlalchemy as sa
from alembic import context, op

TABLES = (
    "conversations",
    "conversation_items",
    "agent_runs",
    "runtime_session_bindings",
    "runtime_run_bindings",
    "run_tool_capabilities",
    "repository_conversations",
    "repository_runs",
)


def renamed(name: str) -> str:
    for old, new in (
        ("agent_sessions", "conversations"),
        ("agent_messages", "conversation_items"),
        ("repository_sessions", "repository_conversations"),
        ("session_id", "conversation_id"),
        ("_id_session", "_id_conversation"),
        ("_session_sequence", "_conversation_sequence"),
        ("_session_queue", "_conversation_queue"),
        ("_session_project", "_conversation_project"),
        ("_message_session", "_message_conversation"),
        ("_active_session", "_active_conversation"),
        ("_run_session", "_run_conversation"),
    ):
        name = name.replace(old, new)
    return name


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Terminology cutover requires an online upgrade for schema reflection.")
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    quote = bind.dialect.identifier_preparer.quote
    op.rename_table("repository_sessions", "repository_conversations")
    for table in TABLES:
        if table != "conversations":
            op.alter_column(table, "session_id", new_column_name="conversation_id")

    if postgres:
        # PostgreSQL rewrites relational dependencies on column rename, but not
        # PL/pgSQL source. Change qualified field references, never JSON keys or
        # immutable event contents. Auth sessions have no such qualified fields
        # in these functions, and keep their separate identity vocabulary.
        functions = (
            bind.execute(
                sa.text(
                    "SELECT pg_get_functiondef(p.oid) FROM pg_proc p "
                    "WHERE p.pronamespace=current_schema()::regnamespace AND p.prokind='f'"
                )
            )
            .scalars()
            .all()
        )
        for definition in functions:
            updated = re.sub(r"(?<=\.)session_id\b", "conversation_id", definition)
            updated = updated.replace("repository_sessions", "repository_conversations")
            updated = updated.replace("project_readable", "members_can_view")
            updated = updated.replace("project_contributable", "members_can_participate")
            if updated != definition:
                op.execute(sa.text(updated))

    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversations_sharing", type_="check")
    op.execute(
        "UPDATE conversations SET sharing = 'members_can_view' WHERE sharing = 'project_readable'"
    )
    op.execute(
        "UPDATE conversations SET sharing = 'members_can_participate' "
        "WHERE sharing = 'project_contributable'"
    )
    with op.batch_alter_table("conversations") as batch:
        batch.create_check_constraint(
            "ck_conversations_sharing",
            "sharing IN ('private', 'members_can_view', 'members_can_participate')",
        )

    inspector = sa.inspect(bind)
    for table in TABLES:
        for index in inspector.get_indexes(table):
            name = index["name"]
            if index.get("duplicates_constraint") or renamed(name) == name:
                continue
            if postgres:
                op.execute(f"ALTER INDEX {quote(name)} RENAME TO {quote(renamed(name))}")
            else:
                options = index.get("dialect_options", {})
                op.drop_index(name, table_name=table)
                op.create_index(
                    renamed(name), table, index["column_names"], unique=index["unique"], **options
                )

    if postgres:
        rows = bind.execute(
            sa.text(
                "SELECT conrelid::regclass::text AS tbl, conname FROM pg_constraint "
                "WHERE connamespace=current_schema()::regnamespace"
            )
        ).all()
        for table, name in rows:
            if table in TABLES and renamed(name) != name:
                op.execute(
                    f"ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(name)} "
                    f"TO {quote(renamed(name))}"
                )
    else:
        # SQLite cannot rename constraints. Recreate their tables using reflected
        # definitions so columns, foreign keys, indexes and values remain intact.
        for name in TABLES:
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            changed = False
            for constraint in table.constraints:
                if constraint.name and renamed(str(constraint.name)) != constraint.name:
                    constraint.name = renamed(str(constraint.name))
                    changed = True
            if changed:
                with op.batch_alter_table(name, copy_from=table, recreate="always"):
                    pass

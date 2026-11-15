"""Frozen library item vocabulary cutover."""

import sqlalchemy as sa
from alembic import context, op

TABLES = {
    "agent_library_entries": "library_items",
    "agent_library_drafts": "library_drafts",
    "agent_library_versions": "library_versions",
    "agent_library_moderation": "library_moderation",
}


def renamed(name: str) -> str:
    return (
        name.replace("agent_library_entries", "library_items")
        .replace("agent_library", "library")
        .replace("entry_id", "item_id")
    )


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute("-- Terminology cutover requires an online upgrade for schema reflection.")
        return
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    quote = bind.dialect.identifier_preparer.quote
    for old, new in TABLES.items():
        op.rename_table(old, new)
    for table in ("library_drafts", "library_versions", "library_moderation"):
        op.alter_column(table, "entry_id", new_column_name="item_id")
    # SQLite table recreation drops triggers. Capture their already-rebound SQL
    # and restore the same guards after constraint names have been updated.
    triggers = (
        []
        if postgres
        else bind.execute(
            sa.text(
                "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name LIKE 'library_%'"
            )
        ).all()
    )
    inspector = sa.inspect(bind)
    for table in TABLES.values():
        for index in inspector.get_indexes(table):
            name = index["name"]
            if index.get("duplicates_constraint") or renamed(name) == name:
                continue
            if postgres:
                op.execute(f"ALTER INDEX {quote(name)} RENAME TO {quote(renamed(name))}")
            else:
                op.drop_index(name, table_name=table)
                op.create_index(
                    renamed(name),
                    table,
                    index["column_names"],
                    unique=index["unique"],
                    **index.get("dialect_options", {}),
                )
    if postgres:
        rows = bind.execute(
            sa.text(
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE connamespace=current_schema()::regnamespace"
            )
        ).all()
        for table, name in rows:
            if table in TABLES.values() and renamed(name) != name:
                op.execute(
                    f"ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(name)} "
                    f"TO {quote(renamed(name))}"
                )
    else:
        for name in TABLES.values():
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            changed = False
            for constraint in table.constraints:
                if constraint.name and renamed(str(constraint.name)) != constraint.name:
                    constraint.name = renamed(str(constraint.name))
                    changed = True
            if changed:
                with op.batch_alter_table(name, copy_from=table, recreate="always"):
                    pass

    if postgres:
        for name in ("agent_library_identity", "agent_library_immutable"):
            op.execute(f"ALTER FUNCTION {quote(name)}() RENAME TO {quote(renamed(name))}")
        triggers = bind.execute(
            sa.text(
                "SELECT tgrelid::regclass::text, tgname FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgrelid IN "
                "(SELECT oid FROM pg_class WHERE relnamespace=current_schema()::regnamespace)"
            )
        ).all()
        for table, name in triggers:
            if table in TABLES.values() and name != renamed(name):
                op.execute(
                    f"ALTER TRIGGER {quote(name)} ON {quote(table)} "
                    f"RENAME TO {quote(renamed(name))}"
                )
    else:
        for name, definition in triggers:
            op.execute(f"DROP TRIGGER IF EXISTS {quote(name)}")
            op.execute(renamed(definition))

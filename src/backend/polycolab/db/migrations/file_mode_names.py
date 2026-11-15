"""Frozen file mode and change set vocabulary cutover."""

import sqlalchemy as sa
from alembic import context, op

TABLES = {
    "linear_workspaces": "collaborative_workspaces",
    "linear_files": "collaborative_files",
    "linear_operations": "collaborative_operations",
    "linear_checkpoints": "collaborative_checkpoints",
    "linear_batches": "change_sets",
    "linear_runs": "collaborative_runs",
    "linear_conversions": "collaborative_conversions",
}


def renamed(name: str) -> str:
    return name.replace("linear_batches", "change_sets").replace("linear_", "collaborative_")


def upgrade() -> None:
    if context.is_offline_mode():
        op.execute("-- Terminology cutover requires an online upgrade for schema reflection.")
        return
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    quote = bind.dialect.identifier_preparer.quote
    op.alter_column("projects", "workspace_mode", new_column_name="file_mode")
    op.execute("UPDATE projects SET file_mode='basic' WHERE file_mode='default'")
    op.execute("UPDATE projects SET file_mode='collaborative' WHERE file_mode='linear'")
    for old, new in TABLES.items():
        op.rename_table(old, new)
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

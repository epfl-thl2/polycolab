"""Frozen execution, idempotency, and usage vocabulary cutover."""

import sqlalchemy as sa
from alembic import context, op

TABLES = {
    "mutation_receipts": "idempotency_records",
    "repository_mutations": "repository_idempotency_records",
    "execution_work_items": "execution_jobs",
}
COLUMNS = {
    "execution_slot_leases": {"work_item_id": "job_id"},
    "execution_fairness_states": {"tenant_kind": "scope_kind", "tenant_id": "scope_id"},
    "hosted_model_requests": {"settle_by": "reconcile_by", "settled_at": "reconciled_at"},
}
AFFECTED = (*TABLES.values(), *COLUMNS)


def renamed(name: str) -> str:
    for old, new in (
        ("mutation_receipts", "idempotency_records"),
        ("mutation_receipt", "idempotency_record"),
        ("repository_mutations", "repository_idempotency_records"),
        ("repository_mutation", "repository_idempotency_record"),
        ("execution_work_items", "execution_jobs"),
        ("execution_work_item", "execution_job"),
        ("work_item_id", "job_id"),
        ("tenant_kind", "scope_kind"),
        ("tenant_id", "scope_id"),
        ("execution_tenant", "execution_scope"),
        ("settle_by", "reconcile_by"),
        ("settled_at", "reconciled_at"),
    ):
        name = name.replace(old, new)
    return name


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("Terminology cutover requires an online upgrade for schema reflection.")
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    quote = bind.dialect.identifier_preparer.quote
    for old, new in TABLES.items():
        op.rename_table(old, new)
    for table, columns in COLUMNS.items():
        for old, new in columns.items():
            op.alter_column(table, old, new_column_name=new)
    if postgres:
        functions = bind.execute(
            sa.text(
                "SELECT proname, pg_get_function_identity_arguments(oid), pg_get_functiondef(oid) "
                "FROM pg_proc WHERE pronamespace=current_schema()::regnamespace AND prokind='f'"
            )
        ).all()
        for name, arguments, definition in functions:
            updated = renamed(definition)
            # Keep the existing function OID so trigger dependencies remain intact.
            # Rename its identity only after replacing its body in place.
            updated = definition.splitlines()[0] + "\n" + updated.split("\n", 1)[1]
            if definition != updated:
                op.execute(sa.text(updated))
            if name != renamed(name):
                op.execute(
                    f"ALTER FUNCTION {quote(name)}({arguments}) RENAME TO {quote(renamed(name))}"
                )
        triggers = bind.execute(
            sa.text(
                "SELECT tgrelid::regclass::text, tgname FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgrelid IN "
                "(SELECT oid FROM pg_class WHERE relnamespace=current_schema()::regnamespace)"
            )
        ).all()
        for table, name in triggers:
            if table in AFFECTED and renamed(name) != name:
                op.execute(
                    f"ALTER TRIGGER {quote(name)} ON {quote(table)} "
                    f"RENAME TO {quote(renamed(name))}"
                )
    else:
        triggers = [
            row
            for row in bind.execute(
                sa.text("SELECT name, sql, tbl_name FROM sqlite_master WHERE type='trigger'")
            ).all()
            if row[2] in AFFECTED
        ]
    inspector = sa.inspect(bind)
    for table in AFFECTED:
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
            if table in AFFECTED and renamed(name) != name:
                op.execute(
                    f"ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(name)} "
                    f"TO {quote(renamed(name))}"
                )
    else:
        for name in AFFECTED:
            table = sa.Table(name, sa.MetaData(), autoload_with=bind)
            changed = False
            for constraint in table.constraints:
                if constraint.name and renamed(str(constraint.name)) != constraint.name:
                    constraint.name = renamed(str(constraint.name))
                    changed = True
            if changed:
                with op.batch_alter_table(name, copy_from=table, recreate="always"):
                    pass

        # Rebuild the captured guards after SQLite recreates tables for constraints.
        for name, definition, _ in triggers:
            op.execute(f"DROP TRIGGER IF EXISTS {quote(name)}")
            op.execute(renamed(definition))
    op.execute(
        "UPDATE operational_metric_aggregates "
        "SET metric_name='polycolab_hosted_reconciliation_total' "
        "WHERE metric_name='polycolab_hosted_settlement_total'"
    )

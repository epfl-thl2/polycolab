"""Name key ownership and execution requesters without changing authority or bytes."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261115_key_names"
down_revision = "local_20261104_provider_profiles"
branch_labels = None
depends_on = None


def renamed(name: str) -> str:
    for old, new in (
        ("external_agent_credentials", "agent_api_keys"),
        ("external_agent_credential", "agent_api_key"),
        ("external_credential_sponsor", "agent_api_key_owner"),
        ("external_credential_scope", "agent_api_key_scope"),
        ("external_agent_", "agent_api_key_"),
        ("sponsor_user_id", "owner_user_id"),
        ("mutation_count", "write_count"),
        ("max_mutations", "max_writes"),
    ):
        name = name.replace(old, new)
    return name


def upgrade() -> None:
    op.rename_table("external_agent_credentials", "agent_api_keys")
    for old, new in (
        ("sponsor_user_id", "owner_user_id"),
        ("mutation_count", "write_count"),
        ("max_mutations", "max_writes"),
    ):
        op.alter_column("agent_api_keys", old, new_column_name=new)
    op.alter_column(
        "execution_work_items", "sponsor_user_id", new_column_name="requested_by_user_id"
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("agent_api_keys", "execution_work_items"):
        for index in inspector.get_indexes(table):
            name = index["name"]
            target = (
                renamed(name)
                if table == "agent_api_keys"
                else name.replace("sponsor_user_id", "requested_by_user_id")
            )
            if target != name:
                op.drop_index(name, table_name=table)
                op.create_index(target, table, index["column_names"], unique=index["unique"])
    # Native column renames preserve values and rewrite constraint expressions.
    # Rebuild only this leaf table to give named constraints canonical names.
    inspector = sa.inspect(bind)
    with op.batch_alter_table("agent_api_keys") as batch:
        for constraint in inspector.get_unique_constraints("agent_api_keys"):
            name = constraint["name"]
            if name and renamed(name) != name:
                batch.drop_constraint(name, type_="unique")
                batch.create_unique_constraint(renamed(name), constraint["column_names"])
        for constraint in inspector.get_check_constraints("agent_api_keys"):
            name = constraint["name"]
            if name and renamed(name) != name:
                batch.drop_constraint(name, type_="check")
                batch.create_check_constraint(renamed(name), constraint["sqltext"])


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

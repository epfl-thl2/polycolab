"""Rename saved provider connections without rewriting encrypted credentials."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261115_provider_connections"
down_revision = "local_20261115_key_names"
branch_labels = None
depends_on = None


def renamed(name: str) -> str:
    return (
        name.replace("provider_profiles", "provider_connections")
        .replace("provider_profile_id", "provider_connection_id")
        .replace("_profile_id", "_provider_connection_id")
    )


def upgrade() -> None:
    op.rename_table("provider_profiles", "provider_connections")
    for table, column in (
        ("agent_runs", "provider_profile_id"),
        ("gateway_run_grants", "profile_id"),
        ("gateway_credential_rewrap_audit", "profile_id"),
        ("legacy_conversation_executions", "profile_id"),
    ):
        op.alter_column(table, column, new_column_name="provider_connection_id")
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = (
        "provider_connections",
        "agent_runs",
        "gateway_run_grants",
        "gateway_credential_rewrap_audit",
        "legacy_conversation_executions",
    )
    for table in tables:
        for index in inspector.get_indexes(table):
            name = index["name"]
            if not index.get("duplicates_constraint") and renamed(name) != name:
                op.drop_index(name, table_name=table)
                op.create_index(renamed(name), table, index["column_names"], unique=index["unique"])

    # Encryption context bytes deliberately retain the gateway-profile namespace.


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

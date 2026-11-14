"""Detach external credentials from retired agent identities, preserving key bytes."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261104_sponsored_keys"
down_revision = "local_20261103_session_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "external_agent_credentials"
    inspector = sa.inspect(op.get_bind())
    # The single-column FK in the frozen baseline is unnamed. Give it a stable
    # reflection name so batch recreation can remove it alongside the binding FK.
    convention = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}
    with op.batch_alter_table(table, naming_convention=convention) as batch:
        for constraint in inspector.get_foreign_keys(table):
            if "agent_id" in constraint["constrained_columns"]:
                name = constraint["name"] or f"fk_{table}_agent_id_external_agent_identities"
                batch.drop_constraint(name, type_="foreignkey")
        batch.drop_constraint("uq_external_credential_agent", type_="unique")
        batch.drop_index("ix_external_agent_credentials_agent_id")
        batch.drop_column("agent_id")
    op.drop_table("external_agent_identities")


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

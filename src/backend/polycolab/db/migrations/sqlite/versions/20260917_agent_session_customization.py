"""Add session-scoped hosted agent configuration to local databases."""

import sqlalchemy as sa
from alembic import op

revision = "local_20260917_custom_agents"
down_revision = "local_20260916_keys_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_sessions", sa.Column("harness", sa.String(32), nullable=True))
    op.add_column("agent_sessions", sa.Column("system_prompt", sa.Text(), nullable=True))
    with op.batch_alter_table("agent_sessions") as batch:
        batch.create_check_constraint(
            "ck_agent_sessions_custom_configuration",
            "(harness IS NULL AND system_prompt IS NULL) OR "
            "(harness = 'codex' AND system_prompt IS NOT NULL)",
        )


def downgrade() -> None:
    raise RuntimeError("Local downgrades are unsupported; restore the pre-upgrade backup.")

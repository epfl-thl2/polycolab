"""Add hosted execution to existing persistent development databases."""

import json
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "local_20260916_hosted"
down_revision = "local_20260916"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("runtime_spec", sa.JSON(), nullable=True))
    op.add_column(
        "gateway_profiles",
        sa.Column("wire_api", sa.String(32), nullable=False, server_default="chat_completions"),
    )
    with op.batch_alter_table("gateway_profiles") as batch:
        batch.alter_column("wire_api", server_default=None)
        batch.create_check_constraint(
            "ck_gateway_wire_api", "wire_api IN ('responses', 'chat_completions')"
        )
    statements = json.loads(Path(__file__).with_name("20260916_hosted_schema.json").read_text())
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Local downgrades are unsupported; restore the pre-upgrade backup.")

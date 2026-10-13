"""Identify compatible executor backends without rewriting frozen run history."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_executors"
down_revision = "20261013_agent_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hosted_executors",
        sa.Column("sandbox_backend", sa.String(16), nullable=False, server_default="microsandbox"),
    )
    op.add_column(
        "hosted_executors",
        sa.Column("sandbox_version", sa.String(128), nullable=False, server_default="0.6.18"),
    )


def downgrade() -> None:
    raise RuntimeError("Drain executors and restore a matching backup before rollback.")

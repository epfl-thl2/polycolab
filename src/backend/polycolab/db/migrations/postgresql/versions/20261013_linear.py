"""Add linear workspaces and optional member-visible conversations."""

from polycolab.db.migrations.linear_schema import upgrade as create_linear_schema

revision = "20261013_linear"
down_revision = "20261013_executors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_linear_schema()


def downgrade() -> None:
    raise RuntimeError("Restore the matching database and project storage backup.")

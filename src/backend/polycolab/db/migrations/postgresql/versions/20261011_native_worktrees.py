"""Native worktree rollout and pinned saved revisions; materialization is separate."""

import sqlalchemy as sa
from alembic import op

revision = "20261011_native_worktrees"
down_revision = "20261008_workspace_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_repositories",
        sa.Column("native_worktrees", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table("repository_runs") as batch:
        batch.add_column(sa.Column("input_revision", sa.String(40), nullable=True))
        batch.add_column(sa.Column("worktree_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_repository_run_worktree", "workspace_tasks", ["worktree_id"], ["id"]
        )


def downgrade() -> None:
    raise RuntimeError("Restore database and repository backups together.")

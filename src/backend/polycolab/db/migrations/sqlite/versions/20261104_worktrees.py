"""Consolidate saved working copies under worktrees without touching Git state."""

from alembic import op

revision = "local_20261104_worktrees"
down_revision = "local_20261104_sponsored_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("project_tasks", "worktrees")
    op.alter_column("worktrees", "archived_at", new_column_name="removed_at")
    op.alter_column("conversations", "task_id", new_column_name="worktree_id")
    op.drop_index("ix_project_tasks_project_id", table_name="worktrees")
    op.create_index("ix_worktrees_project_id", "worktrees", ["project_id"])
    op.drop_index("ix_conversations_task_id", table_name="conversations")
    op.create_index("ix_conversations_worktree_id", "conversations", ["worktree_id"])
    with op.batch_alter_table("worktrees") as batch:
        batch.drop_constraint("uq_project_task_branch", type_="unique")
        batch.create_unique_constraint("uq_worktree_branch", ["project_id", "branch"])
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("fk_agent_sessions_task", type_="foreignkey")
        batch.create_foreign_key("fk_conversations_worktree", "worktrees", ["worktree_id"], ["id"])


def downgrade() -> None:
    raise RuntimeError("Restore the matching database and repository backups and application.")

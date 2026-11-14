"""Consolidate saved working copies under worktrees without touching Git state."""

from alembic import op

revision = "20261104_worktrees"
down_revision = "20261104_sponsored_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("project_tasks", "worktrees")
    op.alter_column("worktrees", "archived_at", new_column_name="removed_at")
    op.alter_column("conversations", "task_id", new_column_name="worktree_id")
    op.execute("ALTER INDEX ix_project_tasks_project_id RENAME TO ix_worktrees_project_id")
    op.execute("ALTER INDEX ix_conversations_task_id RENAME TO ix_conversations_worktree_id")
    op.execute(
        "ALTER TABLE worktrees RENAME CONSTRAINT uq_project_task_branch TO uq_worktree_branch"
    )
    op.execute(
        "ALTER TABLE conversations RENAME CONSTRAINT "
        "fk_agent_sessions_task TO fk_conversations_worktree"
    )
    # PostgreSQL tracks foreign-key targets through table and column renames.
    # Give automatically named constraints the canonical table name as well.
    op.execute("""
DO $worktrees$
DECLARE item RECORD;
BEGIN
 FOR item IN
   SELECT conrelid::regclass::text AS tbl, conname AS name FROM pg_constraint
   WHERE connamespace=current_schema()::regnamespace AND conname LIKE 'project_tasks_%'
 LOOP
   EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', item.tbl, item.name,
                  replace(item.name, 'project_tasks', 'worktrees'));
 END LOOP;
END $worktrees$;
""")


def downgrade() -> None:
    raise RuntimeError("Restore the matching database and repository backups and application.")

"""Durable workspace tasks, shared conversation working copies, and run branches."""

import sqlalchemy as sa
from alembic import op

revision = "20261008_workspace_tasks"
down_revision = "20261006_workspace_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("branch", sa.String(100), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workspace_id", "branch", name="uq_workspace_task_branch"),
    )
    op.create_index("ix_workspace_tasks_workspace_id", "workspace_tasks", ["workspace_id"])
    op.add_column("agent_sessions", sa.Column("task_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_sessions_task", "agent_sessions", "workspace_tasks", ["task_id"], ["id"]
    )
    op.create_index("ix_agent_sessions_task_id", "agent_sessions", ["task_id"])
    op.add_column("repository_runs", sa.Column("branch", sa.String(100), nullable=True))
    op.execute(
        "INSERT INTO workspace_tasks "
        "(id,workspace_id,title,branch,created_by_user_id,created_at,updated_at,arch"
        "ived_at) SELECT s.id,s.project_id,'Saved agent working copy','sessions/' "
        "|| s.id::text,s.created_by_user_id,s.created_at,s.updated_at,NULL FROM "
        "agent_sessions s JOIN repository_sessions r ON r.session_id=s.id"
    )
    op.execute("UPDATE agent_sessions SET task_id=id WHERE id IN (SELECT id FROM workspace_tasks)")
    op.execute("UPDATE repository_runs SET branch='sessions/' || session_id::text")


def downgrade() -> None:
    raise RuntimeError("Restore database and repository backups together.")

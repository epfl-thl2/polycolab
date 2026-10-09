"""Add member workspace repositories and recoverable Git receipts."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261006_workspace_files"
down_revision = "local_20260918_simple_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_repositories",
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "repository_mutations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspace_repositories.workspace_id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("branch", sa.String(100), nullable=False),
        sa.Column("old_commit", sa.String(40), nullable=False),
        sa.Column("new_commit", sa.String(40), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", "key", name="uq_repository_retry"),
    )
    op.create_index(
        "ix_repository_mutations_workspace_id", "repository_mutations", ["workspace_id"]
    )
    op.create_table(
        "repository_sessions",
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("agent_sessions.id"), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspace_repositories.workspace_id"),
            nullable=False,
        ),
        sa.Column("base_commit", sa.String(40), nullable=False),
    )
    op.create_index("ix_repository_sessions_workspace_id", "repository_sessions", ["workspace_id"])
    op.create_table(
        "repository_runs",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("repository_sessions.session_id"), nullable=False
        ),
        sa.Column("input_commit", sa.String(40), nullable=False),
        sa.Column("output_commit", sa.String(40), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("Restore database and repository backups together.")

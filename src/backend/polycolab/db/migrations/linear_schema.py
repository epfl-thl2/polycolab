"""Frozen shared DDL for the first linear workspace migration."""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.add_column(
        "projects", sa.Column("workspace_mode", sa.String(16), nullable=False, server_default="git")
    )
    op.add_column(
        "agent_sessions",
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "linear_workspaces",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("stored_bytes", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "linear_files",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("linear_workspaces.project_id"), nullable=False
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("document", sa.LargeBinary(), nullable=True),
        sa.Column("executable", sa.Boolean(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "linear_operations",
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("linear_workspaces.project_id"), primary_key=True
        ),
        sa.Column("sequence", sa.BigInteger(), primary_key=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "user_id", "request_key", name="uq_linear_operation_request"
        ),
    )
    op.create_table(
        "linear_checkpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("linear_workspaces.project_id"), nullable=False
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("tree", sa.String(40), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "linear_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("linear_workspaces.project_id"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), nullable=True, unique=True),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("base_sequence", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("digest", sa.String(64), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("conflicts", sa.JSON(), nullable=False),
    )
    op.create_table(
        "linear_runs",
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id"), primary_key=True),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("linear_workspaces.project_id"), nullable=False
        ),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column(
            "original_checkpoint_id",
            sa.Uuid(),
            sa.ForeignKey("linear_checkpoints.id"),
            nullable=False,
        ),
        sa.Column(
            "current_checkpoint_id",
            sa.Uuid(),
            sa.ForeignKey("linear_checkpoints.id"),
            nullable=False,
        ),
        sa.Column("refresh_generation", sa.Integer(), nullable=False),
        sa.Column("refresh_data", sa.JSON(), nullable=True),
        sa.Column("applied_sequence", sa.BigInteger(), nullable=True),
    )
    for table in ("linear_files", "linear_checkpoints", "linear_batches", "linear_runs"):
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])

    op.create_table(
        "linear_conversions",
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "source_worktree_id", sa.Uuid(), sa.ForeignKey("project_tasks.id"), nullable=False
        ),
        sa.Column("source_revision", sa.String(40), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
    )

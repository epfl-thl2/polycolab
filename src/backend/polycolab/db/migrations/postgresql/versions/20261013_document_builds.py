"""Private project/worktree document compilation."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_document_builds"
down_revision = "20261013_linear"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_build_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("ready_until", sa.DateTime(timezone=True)),
        sa.Column("image", sa.String(300)),
    )
    op.create_table(
        "document_builds",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("worktree_id", sa.Uuid(), sa.ForeignKey("project_tasks.id"), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(200), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("main_file", sa.String(1000), nullable=False),
        sa.Column("engine", sa.String(20), nullable=False),
        sa.Column("image", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("generation", sa.Uuid()),
        sa.Column("worker_id", sa.String(200)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("physical_until", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(100)),
        sa.UniqueConstraint(
            "project_id",
            "worktree_id",
            "requested_by",
            "request_key",
            name="uq_document_build_retry",
        ),
    )
    for name in ("project_id", "worktree_id", "status", "expires_at"):
        op.create_index(f"ix_document_builds_{name}", "document_builds", [name])


def downgrade() -> None:
    op.drop_table("document_builds")
    op.drop_table("document_build_queue")

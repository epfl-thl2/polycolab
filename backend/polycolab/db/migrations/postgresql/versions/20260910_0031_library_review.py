"""Preserve literature metadata and add attributable Library status reviews."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_library_review"
down_revision = "20260910_credential_rights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("source_identifier", "source_version", "source_locator"):
        op.alter_column("catalogue_revisions", name, nullable=True)
    op.add_column("catalogue_revisions", sa.Column("review_rationale", sa.Text(), nullable=True))
    op.add_column(
        "catalogue_revisions",
        sa.Column("reviewed_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.add_column(
        "catalogue_revisions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_catalogue_source_complete",
        "catalogue_revisions",
        "(source_identifier IS NOT NULL AND source_version IS NOT NULL "
        "AND source_locator IS NOT NULL) OR (source_identifier IS NULL "
        "AND source_version IS NULL AND source_locator IS NULL)",
    )
    op.create_check_constraint(
        "ck_catalogue_review_complete",
        "catalogue_revisions",
        "(review_rationale IS NOT NULL AND reviewed_by_user_id IS NOT NULL "
        "AND reviewed_at IS NOT NULL) OR (review_rationale IS NULL "
        "AND reviewed_by_user_id IS NULL AND reviewed_at IS NULL)",
    )
    op.create_check_constraint(
        "ck_catalogue_status_basis",
        "catalogue_revisions",
        "source_identifier IS NOT NULL OR review_rationale IS NOT NULL",
    )


def downgrade() -> None:
    raise RuntimeError("Library review history cannot be discarded; restore a backup to downgrade")

"""Add chronological and per-assessor assurance read indexes."""

from alembic import op

revision = "20260909_beta_assurance"
down_revision = "20260908_registration_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_rev_endorse_hist",
        "revision_endorsements",
        ["revision_id", "created_at", "id"],
    )
    op.create_index(
        "ix_rev_endorse_current",
        "revision_endorsements",
        ["revision_id", "created_by_user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_corr_assess_hist",
        "correspondence_assessments",
        ["revision_id", "created_at", "id"],
    )
    op.create_index(
        "ix_corr_assess_current",
        "correspondence_assessments",
        [
            "revision_id",
            "created_by_user_id",
            "statement_revision_id",
            "created_at",
            "id",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_corr_assess_current", table_name="correspondence_assessments")
    op.drop_index("ix_corr_assess_hist", table_name="correspondence_assessments")
    op.drop_index("ix_rev_endorse_current", table_name="revision_endorsements")
    op.drop_index("ix_rev_endorse_hist", table_name="revision_endorsements")

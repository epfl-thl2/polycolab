"""Remove tutorial installation bookkeeping; preserve every research workspace."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_unified_deployment"
down_revision = "20260914_login_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("beta_sample_data_installations")


def downgrade() -> None:
    op.create_table(
        "beta_sample_data_installations",
        sa.Column("dataset_version", sa.String(64), primary_key=True),
        sa.Column(
            "owner_account_id", sa.Uuid(), sa.ForeignKey("local_accounts.id"), nullable=False
        ),
        sa.Column(
            "project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False, unique=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_beta_sample_data_installations_owner_account_id",
        "beta_sample_data_installations",
        ["owner_account_id"],
    )

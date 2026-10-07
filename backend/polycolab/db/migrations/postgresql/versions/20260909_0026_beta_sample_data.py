"""Add ordinary logical relation kinds and Beta sample installation identity."""

from alembic import op

revision = "20260909_beta_sample_data"
down_revision = "20260909_beta_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_relation_assertions_relation_type", "relation_assertions", type_="check")
    op.create_check_constraint(
        "ck_relation_assertions_relation_type",
        "relation_assertions",
        "relation_type IN ('DEPENDS_ON','PROVES','ATTEMPTS','REFUTES','USES',"
        "'IMPLIES','EQUIVALENT_TO')",
    )
    op.execute(
        """
CREATE TABLE beta_sample_data_installations (
 dataset_version VARCHAR(64) PRIMARY KEY,
 owner_account_id UUID NOT NULL REFERENCES local_accounts(id),
 project_id UUID NOT NULL UNIQUE REFERENCES projects(id),
 created_at TIMESTAMPTZ NOT NULL
)
"""
    )
    op.create_index(
        "ix_beta_sample_data_installations_owner_account_id",
        "beta_sample_data_installations",
        ["owner_account_id"],
    )


def downgrade() -> None:
    op.drop_table("beta_sample_data_installations")
    op.drop_constraint("ck_relation_assertions_relation_type", "relation_assertions", type_="check")
    op.create_check_constraint(
        "ck_relation_assertions_relation_type",
        "relation_assertions",
        "relation_type IN ('DEPENDS_ON','PROVES','ATTEMPTS','REFUTES','USES')",
    )

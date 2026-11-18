"""Platform-owned model connections and shared daily budget reservations."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261116_model_catalog"
down_revision = "local_20261115_research_helper"
branch_labels = None
depends_on = None

PREVIOUS = (
    "scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip', "
    "'login_ip', 'login_username', 'helper_user', 'helper_global')"
)
CURRENT = PREVIOUS[:-1] + ", 'platform_budget')"


def upgrade() -> None:
    with op.batch_alter_table("provider_connections") as batch:
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("platform_model_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("platform_config", sa.JSON(), nullable=True))
        batch.create_unique_constraint(
            "uq_provider_connections_platform_model_id", ["platform_model_id"]
        )
        batch.create_check_constraint(
            "ck_provider_connection_owner",
            "(user_id IS NOT NULL AND platform_model_id IS NULL AND platform_config IS NULL) "
            "OR (user_id IS NULL AND platform_model_id IS NOT NULL "
            "AND platform_config IS NOT NULL)",
        )
    with op.batch_alter_table("execution_rate_windows") as batch:
        batch.drop_constraint("ck_execution_rate_window_scope", type_="check")
        batch.create_check_constraint("ck_execution_rate_window_scope", CURRENT)


def downgrade() -> None:
    # Platform runs retain their references; remove them explicitly before downgrading.
    with op.batch_alter_table("provider_connections") as batch:
        batch.drop_constraint("ck_provider_connection_owner", type_="check")
        batch.drop_constraint("uq_provider_connections_platform_model_id", type_="unique")
        batch.drop_column("platform_config")
        batch.drop_column("platform_model_id")
        batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)
    op.execute("DELETE FROM execution_rate_windows WHERE scope = 'platform_budget'")
    with op.batch_alter_table("execution_rate_windows") as batch:
        batch.drop_constraint("ck_execution_rate_window_scope", type_="check")
        batch.create_check_constraint("ck_execution_rate_window_scope", PREVIOUS)

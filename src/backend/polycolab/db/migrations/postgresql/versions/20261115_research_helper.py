"""Add admission scopes for the platform research helper."""

from alembic import op

revision = "20261115_research_helper"
down_revision = "20261115_internal_names"
branch_labels = None
depends_on = None

PREVIOUS = (
    "scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip', "
    "'login_ip', 'login_username')"
)
CURRENT = PREVIOUS[:-1] + ", 'helper_user', 'helper_global')"


def upgrade() -> None:
    with op.batch_alter_table("execution_rate_windows") as batch:
        batch.drop_constraint("ck_execution_rate_window_scope", type_="check")
        batch.create_check_constraint("ck_execution_rate_window_scope", CURRENT)


def downgrade() -> None:
    op.execute("DELETE FROM execution_rate_windows WHERE scope IN ('helper_user', 'helper_global')")
    with op.batch_alter_table("execution_rate_windows") as batch:
        batch.drop_constraint("ck_execution_rate_window_scope", type_="check")
        batch.create_check_constraint("ck_execution_rate_window_scope", PREVIOUS)

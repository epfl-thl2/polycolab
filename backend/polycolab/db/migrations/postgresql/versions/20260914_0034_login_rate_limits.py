"""Add durable local-login admission scopes."""

from alembic import op

revision = "20260914_login_rate_limits"
down_revision = "20260911_contribution_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE execution_rate_windows DROP CONSTRAINT ck_execution_rate_window_scope")
    op.execute("""
ALTER TABLE execution_rate_windows ADD CONSTRAINT ck_execution_rate_window_scope
CHECK (scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip',
                 'login_ip', 'login_username'))
""")


def downgrade() -> None:
    op.execute("DELETE FROM execution_rate_windows WHERE scope IN ('login_ip', 'login_username')")
    op.execute("ALTER TABLE execution_rate_windows DROP CONSTRAINT ck_execution_rate_window_scope")
    op.execute("""
ALTER TABLE execution_rate_windows ADD CONSTRAINT ck_execution_rate_window_scope
CHECK (scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip'))
""")

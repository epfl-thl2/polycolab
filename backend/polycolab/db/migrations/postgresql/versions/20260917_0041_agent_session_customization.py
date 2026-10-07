"""Persist session-scoped hosted agent instructions and harness selection."""

from alembic import op

revision = "20260917_custom_agents"
down_revision = "20260916_merge_keys_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_sessions ADD COLUMN harness VARCHAR(32)")
    op.execute("ALTER TABLE agent_sessions ADD COLUMN system_prompt TEXT")
    op.execute(
        "ALTER TABLE agent_sessions ADD CONSTRAINT ck_agent_sessions_custom_configuration "
        "CHECK ((harness IS NULL AND system_prompt IS NULL) OR "
        "(harness = 'codex' AND system_prompt IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_sessions DROP CONSTRAINT ck_agent_sessions_custom_configuration")
    op.execute("ALTER TABLE agent_sessions DROP COLUMN system_prompt")
    op.execute("ALTER TABLE agent_sessions DROP COLUMN harness")

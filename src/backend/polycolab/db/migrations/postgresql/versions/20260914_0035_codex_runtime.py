"""Preserve historical provider protocols and pin new hosted execution metadata."""

from alembic import op

revision = "20260914_codex_runtime"
down_revision = "20260914_login_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE gateway_profiles ADD COLUMN wire_api VARCHAR(32) "
        "NOT NULL DEFAULT 'chat_completions'"
    )
    op.execute("ALTER TABLE gateway_profiles ALTER COLUMN wire_api SET DEFAULT 'responses'")
    op.execute(
        "ALTER TABLE gateway_profiles ADD CONSTRAINT ck_gateway_wire_api "
        "CHECK (wire_api IN ('responses', 'chat_completions'))"
    )
    op.execute("ALTER TABLE agent_runs ADD COLUMN runtime_spec JSON")
    op.execute("""
CREATE FUNCTION protect_agent_runtime_spec() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.runtime_spec::text IS DISTINCT FROM OLD.runtime_spec::text THEN
        RAISE EXCEPTION 'agent runtime specification is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER agent_runtime_spec_immutable BEFORE UPDATE ON agent_runs
FOR EACH ROW EXECUTE FUNCTION protect_agent_runtime_spec();
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER agent_runtime_spec_immutable ON agent_runs")
    op.execute("DROP FUNCTION protect_agent_runtime_spec()")
    op.execute("ALTER TABLE agent_runs DROP COLUMN runtime_spec")
    op.execute("ALTER TABLE gateway_profiles DROP COLUMN wire_api")

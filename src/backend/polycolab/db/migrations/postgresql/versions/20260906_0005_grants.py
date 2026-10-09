"""Immutable requested authority and exact run output scope."""

from alembic import op

revision = "20260906_grants"
down_revision = "20260906_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE run_write_grants (
 run_id UUID PRIMARY KEY REFERENCES agent_runs(id),
 request JSON NOT NULL,
 request_digest VARCHAR(64) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
)
""")
    op.execute("""
CREATE TABLE run_revision_outputs (
 run_id UUID NOT NULL REFERENCES agent_runs(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (run_id, revision_id)
)
""")
    for table in ("run_write_grants", "run_revision_outputs"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION validate_run_grant_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM agent_runs WHERE id = NEW.run_id
                AND xmin::text = pg_current_xact_id()::text)
 THEN RAISE EXCEPTION 'grant must be recorded with run intent'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER run_grant_insert BEFORE INSERT ON run_write_grants
FOR EACH ROW EXECUTE FUNCTION validate_run_grant_insert()
""")
    op.execute("""
CREATE FUNCTION validate_run_revision_output() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
   SELECT 1 FROM object_revisions r JOIN contribution_envelopes c ON c.id = r.contribution_id
   WHERE r.id = NEW.revision_id AND c.id = NEW.contribution_id AND c.run_id = NEW.run_id
     AND c.actor_kind = 'AGENT'
 ) THEN RAISE EXCEPTION 'run output attribution mismatch'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER run_revision_output_insert BEFORE INSERT ON run_revision_outputs
FOR EACH ROW EXECUTE FUNCTION validate_run_revision_output()
""")


def downgrade() -> None:
    raise RuntimeError("Retain run authority and output history; disable new grants instead.")

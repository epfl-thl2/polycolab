"""Bind completed verification artifact outputs to their originating agent run."""

from alembic import op

revision = "20260908_run_artifact_outputs"
down_revision = "20260908_context_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE run_artifact_outputs (
 run_id UUID NOT NULL REFERENCES agent_runs(id),
 artifact_id UUID NOT NULL REFERENCES artifacts(id),
 result_id UUID NOT NULL REFERENCES verification_results(id),
 created_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (run_id, artifact_id),
 CONSTRAINT uq_run_artifact_output_artifact UNIQUE (artifact_id)
)
""")
    op.execute("""
CREATE INDEX ix_run_artifact_outputs_result_id ON run_artifact_outputs(result_id)
""")
    op.execute("""
CREATE FUNCTION validate_run_artifact_output() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NOT EXISTS (
   SELECT 1
   FROM verification_output_artifacts output
   JOIN verification_jobs job ON job.id = output.job_id
   JOIN contribution_envelopes contribution ON contribution.id = job.contribution_id
   JOIN artifacts artifact ON artifact.id = output.artifact_id
   WHERE output.artifact_id = NEW.artifact_id
     AND output.result_id = NEW.result_id
     AND contribution.run_id = NEW.run_id
     AND contribution.actor_kind = 'AGENT'
     AND artifact.state = 'COMMITTED'
 ) THEN RAISE EXCEPTION 'run artifact output attribution mismatch'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER run_artifact_output_insert BEFORE INSERT ON run_artifact_outputs
FOR EACH ROW EXECUTE FUNCTION validate_run_artifact_output()
""")
    op.execute("""
CREATE TRIGGER run_artifact_outputs_immutable
BEFORE UPDATE OR DELETE ON run_artifact_outputs
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")


def downgrade() -> None:
    raise RuntimeError("Exact run artifact output history is durable.")

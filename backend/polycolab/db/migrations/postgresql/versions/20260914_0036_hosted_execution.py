"""Durable hosted provider dispatch ledger."""

from alembic import op

revision = "20260914_hosted_execution"
down_revision = "20260914_codex_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        _SLOT_VALIDATION.replace(
            "NEW.safe_release_at = run.deadline_at",
            "NEW.safe_release_at = run.deadline_at + CASE WHEN "
            "run.runtime_spec->>'engine' = 'codex' THEN interval '30 seconds' "
            "ELSE interval '0 seconds' END",
        )
    )
    op.execute("""
CREATE TABLE hosted_model_requests (
 id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES agent_runs(id),
 generation INTEGER NOT NULL, request_key VARCHAR(200) NOT NULL,
 request_digest VARCHAR(64) NOT NULL, state VARCHAR(16) NOT NULL,
 input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, cost_microusd INTEGER NOT NULL,
 dispatched_at TIMESTAMPTZ NOT NULL, settle_by TIMESTAMPTZ NOT NULL, settled_at TIMESTAMPTZ,
 CONSTRAINT uq_hosted_model_request_key UNIQUE(run_id, request_key),
 CONSTRAINT ck_hosted_request_state CHECK(state IN ('PENDING','COMPLETED','UNCERTAIN')),
 CONSTRAINT ck_hosted_request_usage CHECK(
 generation >= 1 AND input_tokens >= 0 AND output_tokens >= 0 AND cost_microusd >= 0)
);
CREATE FUNCTION guard_hosted_dispatch() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'hosted dispatch history is immutable'; END IF;
 IF OLD.state <> 'PENDING' OR NEW.state NOT IN ('COMPLETED','UNCERTAIN')
    OR NEW.settled_at IS NULL
    OR ROW(NEW.id, NEW.run_id, NEW.generation, NEW.request_key, NEW.request_digest,
           NEW.dispatched_at, NEW.settle_by)
       IS DISTINCT FROM ROW(OLD.id, OLD.run_id, OLD.generation, OLD.request_key,
           OLD.request_digest, OLD.dispatched_at, OLD.settle_by)
 THEN RAISE EXCEPTION 'invalid hosted dispatch settlement'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER hosted_dispatch_history BEFORE UPDATE OR DELETE ON hosted_model_requests
FOR EACH ROW EXECUTE FUNCTION guard_hosted_dispatch();
CREATE INDEX ix_hosted_model_requests_run_id ON hosted_model_requests(run_id);
CREATE TABLE hosted_executors (
 worker_id VARCHAR(200) PRIMARY KEY, image_digest VARCHAR(64) NOT NULL,
 capacity INTEGER NOT NULL CHECK(capacity BETWEEN 1 AND 64), expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ix_hosted_executors_expires_at ON hosted_executors(expires_at);
CREATE TABLE hosted_run_artifacts (
 artifact_id UUID PRIMARY KEY REFERENCES artifacts(id),
 run_id UUID NOT NULL REFERENCES agent_runs(id),
 generation INTEGER NOT NULL, path VARCHAR(240) NOT NULL, display_name VARCHAR(200) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, CONSTRAINT uq_hosted_export_path UNIQUE(run_id, generation, path)
);
CREATE INDEX ix_hosted_run_artifacts_run_id ON hosted_run_artifacts(run_id);
CREATE TRIGGER hosted_exports_immutable BEFORE UPDATE OR DELETE ON hosted_run_artifacts
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
""")


def downgrade() -> None:
    op.execute(_SLOT_VALIDATION)
    op.execute("DROP TABLE hosted_run_artifacts")
    op.execute("DROP TABLE hosted_executors")
    op.execute("DROP TABLE hosted_model_requests")
    op.execute("DROP FUNCTION guard_hosted_dispatch()")


_SLOT_VALIDATION = """
CREATE OR REPLACE FUNCTION validate_execution_slot_lease() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'INSERT' THEN
   IF NEW.agent_run_id IS NOT NULL AND NOT EXISTS (
     SELECT 1 FROM execution_work_items item JOIN agent_runs run ON run.id = item.agent_run_id
     WHERE item.id = NEW.work_item_id AND item.workload_class = 'AGENT'
       AND NEW.workload_class = item.workload_class
       AND item.agent_run_id = NEW.agent_run_id AND run.lease_generation = NEW.generation
       AND NEW.owner_id = run.lease_owner
       AND NEW.acquired_at = run.lease_acquired_at
       AND NEW.lease_expires_at = run.lease_expires_at
       AND NEW.safe_release_at = run.deadline_at
   ) THEN RAISE EXCEPTION 'execution agent slot identity mismatch'; END IF;
   IF NEW.verification_attempt_id IS NOT NULL AND NOT EXISTS (
     SELECT 1 FROM execution_work_items item
     JOIN verification_attempts attempt ON attempt.job_id = item.verification_job_id
     JOIN verification_jobs job ON job.id = item.verification_job_id
     WHERE item.id = NEW.work_item_id AND item.workload_class = NEW.workload_class
       AND attempt.id = NEW.verification_attempt_id AND attempt.generation = NEW.generation
       AND NEW.owner_id = attempt.controller_id
       AND NEW.acquired_at = attempt.started_at
       AND NEW.lease_expires_at = attempt.lease_expires_at
       AND NEW.safe_release_at = LEAST(
         job.deadline_at, attempt.started_at + make_interval(secs => job.wall_seconds)
       )
   ) THEN RAISE EXCEPTION 'execution verification slot identity mismatch'; END IF;
 ELSE
   IF NEW.id <> OLD.id OR NEW.work_item_id <> OLD.work_item_id
      OR NEW.workload_class <> OLD.workload_class
      OR NEW.agent_run_id IS DISTINCT FROM OLD.agent_run_id
      OR NEW.verification_attempt_id IS DISTINCT FROM OLD.verification_attempt_id
      OR NEW.generation <> OLD.generation OR NEW.owner_id <> OLD.owner_id
      OR NEW.acquired_at <> OLD.acquired_at OR NEW.safe_release_at <> OLD.safe_release_at
      OR NEW.lease_expires_at < OLD.lease_expires_at
      OR (OLD.termination_confirmed_at IS NOT NULL
          AND NEW.termination_confirmed_at IS DISTINCT FROM OLD.termination_confirmed_at)
      OR (OLD.released_at IS NOT NULL AND NEW.released_at IS DISTINCT FROM OLD.released_at)
   THEN RAISE EXCEPTION 'execution slot identity or history mutation'; END IF;
 END IF;
 RETURN NEW;
END $$
"""

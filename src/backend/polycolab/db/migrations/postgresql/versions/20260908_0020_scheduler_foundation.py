"""Add private durable scheduling work, fairness and safe slot foundations."""

from alembic import op

revision = "20260908_scheduler_foundation"
down_revision = "20260908_credential_rewrap_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_runs ADD COLUMN lease_acquired_at TIMESTAMPTZ")
    op.execute("""
CREATE TABLE execution_work_items (
 id UUID PRIMARY KEY,
 agent_run_id UUID UNIQUE REFERENCES agent_runs(id),
 verification_job_id UUID UNIQUE REFERENCES verification_jobs(id),
 sponsor_user_id UUID NOT NULL REFERENCES users(id),
 project_id UUID NOT NULL REFERENCES projects(id),
 workload_class VARCHAR(24) NOT NULL,
 policy_version INTEGER NOT NULL,
 reserved_cost BIGINT NOT NULL,
 agent_model_tokens BIGINT,
 agent_provider_cost_microusd BIGINT,
 verification_cpu_seconds BIGINT,
 verification_memory_byte_seconds BIGINT,
 wall_seconds BIGINT NOT NULL,
 queued_at TIMESTAMPTZ NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_execution_work_item_identity CHECK
   ((agent_run_id IS NOT NULL AND verification_job_id IS NULL) OR
    (agent_run_id IS NULL AND verification_job_id IS NOT NULL)),
 CONSTRAINT ck_execution_work_item_class CHECK
   (workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')),
 CONSTRAINT ck_execution_work_item_policy CHECK (policy_version >= 1),
 CONSTRAINT ck_execution_work_item_cost CHECK (reserved_cost >= 1),
 CONSTRAINT ck_execution_work_item_wall CHECK (wall_seconds >= 1),
 CONSTRAINT ck_execution_work_item_resource_shape CHECK
   ((workload_class = 'AGENT' AND agent_run_id IS NOT NULL
     AND agent_model_tokens IS NOT NULL AND agent_provider_cost_microusd IS NOT NULL
     AND verification_cpu_seconds IS NULL AND verification_memory_byte_seconds IS NULL) OR
    (workload_class <> 'AGENT' AND verification_job_id IS NOT NULL
     AND agent_model_tokens IS NULL AND agent_provider_cost_microusd IS NULL
     AND verification_cpu_seconds IS NOT NULL
     AND verification_memory_byte_seconds IS NOT NULL)),
 CONSTRAINT ck_execution_work_item_agent_tokens CHECK
   (agent_model_tokens IS NULL OR agent_model_tokens >= 1),
 CONSTRAINT ck_execution_work_item_agent_cost CHECK
   (agent_provider_cost_microusd IS NULL OR agent_provider_cost_microusd >= 1),
 CONSTRAINT ck_execution_work_item_verification_cpu CHECK
   (verification_cpu_seconds IS NULL OR verification_cpu_seconds >= 1),
 CONSTRAINT ck_execution_work_item_verification_memory CHECK
   (verification_memory_byte_seconds IS NULL OR verification_memory_byte_seconds >= 1)
)
""")
    op.execute(
        "CREATE INDEX ix_execution_work_items_sponsor_user_id "
        "ON execution_work_items(sponsor_user_id)"
    )
    op.execute(
        "CREATE INDEX ix_execution_work_items_project_id ON execution_work_items(project_id)"
    )
    op.execute(
        "CREATE INDEX ix_execution_work_items_queue "
        "ON execution_work_items(workload_class, queued_at, id)"
    )
    op.execute("""
CREATE TABLE execution_class_states (
 workload_class VARCHAR(24) PRIMARY KEY,
 active_policy_version INTEGER NOT NULL,
 virtual_runtime_floor BIGINT NOT NULL,
 scheduling_sequence BIGINT NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_execution_class_name CHECK
   (workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')),
 CONSTRAINT ck_execution_class_policy CHECK (active_policy_version >= 1),
 CONSTRAINT ck_execution_class_floor CHECK (virtual_runtime_floor >= 0),
 CONSTRAINT ck_execution_class_sequence CHECK (scheduling_sequence >= 0)
)
""")
    op.execute("""
CREATE TABLE execution_fairness_states (
 workload_class VARCHAR(24) NOT NULL REFERENCES execution_class_states(workload_class),
 tenant_kind VARCHAR(16) NOT NULL,
 tenant_id UUID NOT NULL,
 policy_version INTEGER NOT NULL,
 virtual_runtime BIGINT NOT NULL,
 last_served_at TIMESTAMPTZ,
 updated_at TIMESTAMPTZ NOT NULL,
 PRIMARY KEY (workload_class, tenant_kind, tenant_id),
 CONSTRAINT ck_execution_tenant_kind CHECK (tenant_kind IN ('USER','WORKSPACE')),
 CONSTRAINT ck_execution_fairness_policy CHECK (policy_version >= 1),
 CONSTRAINT ck_execution_fairness_runtime CHECK (virtual_runtime >= 0)
)
""")
    op.execute("""
CREATE TABLE execution_slot_leases (
 id UUID PRIMARY KEY,
 work_item_id UUID NOT NULL REFERENCES execution_work_items(id),
 workload_class VARCHAR(24) NOT NULL,
 agent_run_id UUID REFERENCES agent_runs(id),
 verification_attempt_id UUID UNIQUE REFERENCES verification_attempts(id),
 generation INTEGER NOT NULL,
 owner_id VARCHAR(200) NOT NULL,
 acquired_at TIMESTAMPTZ NOT NULL,
 lease_expires_at TIMESTAMPTZ NOT NULL,
 safe_release_at TIMESTAMPTZ NOT NULL,
 termination_confirmed_at TIMESTAMPTZ,
 released_at TIMESTAMPTZ,
 CONSTRAINT uq_execution_slot_agent_attempt UNIQUE (agent_run_id, generation),
 CONSTRAINT ck_execution_slot_class CHECK
   (workload_class IN ('AGENT','INTERACTIVE_LEAN','BACKGROUND_LEAN','PYTHON')),
 CONSTRAINT ck_execution_slot_generation CHECK (generation >= 1),
 CONSTRAINT ck_execution_slot_identity CHECK
   ((agent_run_id IS NOT NULL AND verification_attempt_id IS NULL) OR
    (agent_run_id IS NULL AND verification_attempt_id IS NOT NULL)),
 CONSTRAINT ck_execution_slot_lease_time CHECK (lease_expires_at >= acquired_at),
 CONSTRAINT ck_execution_slot_safe_bound CHECK (lease_expires_at <= safe_release_at),
 CONSTRAINT ck_execution_slot_termination_time CHECK
   (termination_confirmed_at IS NULL OR termination_confirmed_at >= acquired_at),
 CONSTRAINT ck_execution_slot_release_time CHECK
   (released_at IS NULL OR released_at >= acquired_at),
 CONSTRAINT ck_execution_slot_release_safety CHECK
   (released_at IS NULL OR termination_confirmed_at IS NOT NULL
    OR released_at >= safe_release_at),
 CONSTRAINT ck_execution_slot_release_after_termination CHECK
   (released_at IS NULL OR termination_confirmed_at IS NULL
    OR released_at >= termination_confirmed_at)
)
""")
    op.execute(
        "CREATE INDEX ix_execution_slot_leases_work_item_id ON execution_slot_leases(work_item_id)"
    )
    op.execute(
        "CREATE INDEX ix_execution_slot_leases_lease_expires_at "
        "ON execution_slot_leases(lease_expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_execution_slot_leases_safe_release_at "
        "ON execution_slot_leases(safe_release_at)"
    )
    op.execute(
        "CREATE INDEX ix_execution_slot_capacity "
        "ON execution_slot_leases(workload_class, released_at, safe_release_at)"
    )

    op.execute("""
CREATE FUNCTION validate_execution_work_item() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected_class TEXT;
BEGIN
 IF NEW.agent_run_id IS NOT NULL THEN
   IF NOT EXISTS (
     SELECT 1 FROM agent_runs run
     WHERE run.id = NEW.agent_run_id
       AND run.requested_by_user_id = NEW.sponsor_user_id
       AND run.project_id = NEW.project_id
       AND run.created_at = NEW.queued_at
       AND run.deadline_at IS NOT NULL
   ) THEN RAISE EXCEPTION 'execution agent work identity mismatch'; END IF;
 ELSE
   SELECT CASE
     WHEN environment.language = 'PYTHON' THEN 'PYTHON'
     WHEN job.purpose = 'LEAN_CHECK' AND contribution.actor_kind = 'HUMAN'
       THEN 'INTERACTIVE_LEAN'
     ELSE 'BACKGROUND_LEAN'
   END INTO expected_class
   FROM verification_jobs job
   JOIN verification_environments environment ON environment.id = job.environment_id
   JOIN contribution_envelopes contribution ON contribution.id = job.contribution_id
   JOIN research_scopes scope ON scope.id = job.ownership_scope_id
   WHERE job.id = NEW.verification_job_id
     AND job.sponsor_user_id = NEW.sponsor_user_id
     AND scope.project_id = NEW.project_id
     AND job.queued_at = NEW.queued_at
     AND job.cpu_seconds = NEW.verification_cpu_seconds
     AND job.memory_bytes * job.wall_seconds = NEW.verification_memory_byte_seconds
     AND job.wall_seconds = NEW.wall_seconds;
   IF expected_class IS NULL OR expected_class <> NEW.workload_class THEN
     RAISE EXCEPTION 'execution verification work identity mismatch';
   END IF;
 END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER execution_work_item_insert BEFORE INSERT ON execution_work_items
FOR EACH ROW EXECUTE FUNCTION validate_execution_work_item()
""")
    op.execute("""
CREATE TRIGGER execution_work_items_immutable
BEFORE UPDATE OR DELETE ON execution_work_items
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")

    op.execute("""
CREATE FUNCTION validate_execution_fairness_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.tenant_kind = 'USER' AND NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.tenant_id)
 THEN RAISE EXCEPTION 'execution fairness user missing'; END IF;
 IF NEW.tenant_kind = 'WORKSPACE' AND NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.tenant_id)
 THEN RAISE EXCEPTION 'execution fairness workspace missing'; END IF;
 IF TG_OP = 'UPDATE' AND (
   NEW.workload_class <> OLD.workload_class OR NEW.tenant_kind <> OLD.tenant_kind
   OR NEW.tenant_id <> OLD.tenant_id OR NEW.policy_version < OLD.policy_version
   OR NEW.virtual_runtime < OLD.virtual_runtime
 ) THEN RAISE EXCEPTION 'execution fairness state cannot move backward'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER execution_fairness_state_write BEFORE INSERT OR UPDATE
ON execution_fairness_states FOR EACH ROW EXECUTE FUNCTION validate_execution_fairness_state()
""")
    op.execute("""
CREATE TRIGGER execution_fairness_states_no_delete BEFORE DELETE ON execution_fairness_states
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE FUNCTION validate_execution_class_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'UPDATE' AND (
   NEW.workload_class <> OLD.workload_class
   OR NEW.active_policy_version < OLD.active_policy_version
   OR NEW.virtual_runtime_floor < OLD.virtual_runtime_floor
   OR NEW.scheduling_sequence < OLD.scheduling_sequence
 ) THEN RAISE EXCEPTION 'execution class state cannot move backward'; END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER execution_class_state_write BEFORE UPDATE ON execution_class_states
FOR EACH ROW EXECUTE FUNCTION validate_execution_class_state()
""")
    op.execute("""
CREATE TRIGGER execution_class_states_no_delete BEFORE DELETE ON execution_class_states
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")
    op.execute("""
CREATE FUNCTION validate_execution_slot_lease() RETURNS trigger LANGUAGE plpgsql AS $$
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
""")
    op.execute("""
CREATE TRIGGER execution_slot_lease_write BEFORE INSERT OR UPDATE
ON execution_slot_leases FOR EACH ROW EXECUTE FUNCTION validate_execution_slot_lease()
""")
    op.execute("""
CREATE TRIGGER execution_slot_leases_no_delete BEFORE DELETE ON execution_slot_leases
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")


def downgrade() -> None:
    raise RuntimeError("Retain durable scheduler history and fairness state.")

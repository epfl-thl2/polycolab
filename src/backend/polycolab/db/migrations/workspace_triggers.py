"""Frozen PostgreSQL integrity functions for the workspace-only schema."""

from alembic import op


def restore_triggers() -> None:
    op.execute("""
CREATE OR REPLACE FUNCTION protect_artifact_identity() RETURNS trigger AS $$
BEGIN
IF TG_OP = 'DELETE' OR
 NEW.id IS DISTINCT FROM OLD.id OR
 NEW.project_id IS DISTINCT FROM OLD.project_id OR
 NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id OR
 NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
 NEW.byte_length IS DISTINCT FROM OLD.byte_length OR
 NEW.media_type IS DISTINCT FROM OLD.media_type OR
 NEW.storage_key IS DISTINCT FROM OLD.storage_key OR
 NEW.environment::jsonb IS DISTINCT FROM OLD.environment::jsonb OR
 NEW.created_at IS DISTINCT FROM OLD.created_at OR
 NEW.expires_at IS DISTINCT FROM OLD.expires_at
THEN RAISE EXCEPTION 'artifact identity and integrity metadata are immutable'; END IF;
IF OLD.state = 'STAGING' AND NEW.state = 'STAGING' THEN
 IF OLD.verified_at IS NOT NULL AND NEW.verified_at IS DISTINCT FROM OLD.verified_at
 THEN RAISE EXCEPTION 'artifact verification is immutable once recorded'; END IF;
ELSIF OLD.state = 'STAGING' AND NEW.state IN ('COMMITTED','DELETING') THEN NULL;
ELSIF OLD.state = 'DELETING' AND NEW.state = 'DELETED' THEN NULL;
ELSE RAISE EXCEPTION 'invalid artifact lifecycle transition'; END IF;
RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE OR REPLACE FUNCTION validate_execution_work_item() RETURNS trigger LANGUAGE plpgsql AS $$
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
 END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
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
       AND NEW.safe_release_at = run.deadline_at + CASE WHEN
         run.runtime_spec->>'engine' = 'codex' THEN interval '30 seconds'
         ELSE interval '0 seconds' END
   ) THEN RAISE EXCEPTION 'execution agent slot identity mismatch'; END IF;
 ELSE
   IF NEW.id <> OLD.id OR NEW.work_item_id <> OLD.work_item_id
      OR NEW.workload_class <> OLD.workload_class
      OR NEW.agent_run_id IS DISTINCT FROM OLD.agent_run_id
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
CREATE OR REPLACE FUNCTION external_agent_credential_grant_immutable() RETURNS trigger AS $$
BEGIN
 IF NEW.project_id IS DISTINCT FROM OLD.project_id
 OR NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
 OR NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id
 OR NEW.agent_id IS DISTINCT FROM OLD.agent_id
 OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
 OR NEW.fixed_rights::jsonb IS DISTINCT FROM OLD.fixed_rights::jsonb
 OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
 OR NEW.max_requests IS DISTINCT FROM OLD.max_requests
 OR NEW.max_mutations IS DISTINCT FROM OLD.max_mutations
 THEN RAISE EXCEPTION 'external agent credential grant is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
""")
    op.execute("""
CREATE OR REPLACE FUNCTION validate_context_manifest_artifact() RETURNS trigger AS $$
DECLARE
 expected_id TEXT;
 manifest_project UUID;
 artifact_project UUID;
 artifact_state VARCHAR(16);
BEGIN
 SELECT cm.artifact_ids ->> NEW.position, cm.project_id, a.project_id, a.state
 INTO expected_id, manifest_project, artifact_project, artifact_state
 FROM context_manifests cm
 JOIN artifacts a ON a.id = NEW.artifact_id
 WHERE cm.id = NEW.manifest_id;
 IF expected_id IS DISTINCT FROM NEW.artifact_id::text
    OR artifact_project IS DISTINCT FROM manifest_project
    OR artifact_state <> 'COMMITTED' THEN
  RAISE EXCEPTION 'context manifest artifact mismatch';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")

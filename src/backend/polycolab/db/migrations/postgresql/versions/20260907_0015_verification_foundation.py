"""Shared immutable verification identity and lifecycle foundation."""

from alembic import op

revision = "20260907_verification_foundation"
down_revision = "20260907_artifact_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _environments_and_jobs()
    _job_members_and_history()
    _integrity_triggers()


def _environments_and_jobs() -> None:
    op.execute("""
CREATE TABLE verification_environments (
 id UUID PRIMARY KEY,
 language VARCHAR(16) NOT NULL,
 image_digest VARCHAR(64) NOT NULL UNIQUE,
 toolchain_version VARCHAR(200) NOT NULL,
 dependency_lock_digest VARCHAR(64) NOT NULL,
 build_digest VARCHAR(64) NOT NULL,
 platform_identity VARCHAR(200) NOT NULL,
 max_cpu_count INTEGER NOT NULL,
 max_cpu_seconds INTEGER NOT NULL,
 max_wall_seconds INTEGER NOT NULL,
 max_memory_bytes BIGINT NOT NULL,
 max_process_count INTEGER NOT NULL,
 max_disk_bytes BIGINT NOT NULL,
 max_output_bytes BIGINT NOT NULL,
 max_log_bytes BIGINT NOT NULL,
 max_output_files INTEGER NOT NULL,
 available BOOLEAN NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 availability_changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT ck_verification_environment_language CHECK (language IN ('PYTHON','LEAN')),
 CONSTRAINT ck_verification_environment_image_digest CHECK (length(image_digest) = 64),
 CONSTRAINT ck_verification_environment_dependency_digest
  CHECK (length(dependency_lock_digest) = 64),
 CONSTRAINT ck_verification_environment_build_digest CHECK (length(build_digest) = 64),
 CONSTRAINT ck_verification_environment_cpu_count CHECK (max_cpu_count >= 1),
 CONSTRAINT ck_verification_environment_cpu_seconds CHECK (max_cpu_seconds >= 1),
 CONSTRAINT ck_verification_environment_wall_seconds CHECK (max_wall_seconds >= 1),
 CONSTRAINT ck_verification_environment_memory CHECK (max_memory_bytes >= 1),
 CONSTRAINT ck_verification_environment_processes CHECK (max_process_count >= 1),
 CONSTRAINT ck_verification_environment_disk CHECK (max_disk_bytes >= 1),
 CONSTRAINT ck_verification_environment_output CHECK (max_output_bytes >= 0),
 CONSTRAINT ck_verification_environment_log CHECK (max_log_bytes >= 0),
 CONSTRAINT ck_verification_environment_files CHECK (max_output_files >= 0)
)
""")
    op.execute(
        "CREATE INDEX ix_verification_environments_available "
        "ON verification_environments(available)"
    )
    op.execute("""
CREATE TABLE verification_jobs (
 id UUID PRIMARY KEY,
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 sponsor_user_id UUID NOT NULL REFERENCES users(id),
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 work_target_revision_id UUID NOT NULL REFERENCES object_revisions(id),
 research_attempt_revision_id UUID NULL REFERENCES research_attempt_revisions(revision_id),
 environment_id UUID NOT NULL REFERENCES verification_environments(id),
 purpose VARCHAR(32) NOT NULL,
 evidence_scope VARCHAR(4000) NOT NULL,
 entrypoint VARCHAR(240) NOT NULL,
 arguments JSON NOT NULL,
 seed BIGINT NULL,
 manifest_digest VARCHAR(64) NOT NULL,
 request_digest VARCHAR(64) NOT NULL,
 retry_key_digest VARCHAR(64) NOT NULL,
 contract_version INTEGER NOT NULL,
 cpu_count INTEGER NOT NULL,
 cpu_seconds INTEGER NOT NULL,
 wall_seconds INTEGER NOT NULL,
 memory_bytes BIGINT NOT NULL,
 process_count INTEGER NOT NULL,
 disk_bytes BIGINT NOT NULL,
 output_bytes BIGINT NOT NULL,
 log_bytes BIGINT NOT NULL,
 output_files INTEGER NOT NULL,
 state VARCHAR(16) NOT NULL,
 current_generation INTEGER NOT NULL,
 event_sequence INTEGER NOT NULL,
 max_attempts INTEGER NOT NULL,
 queued_at TIMESTAMP WITH TIME ZONE NOT NULL,
 deadline_at TIMESTAMP WITH TIME ZONE NOT NULL,
 terminal_at TIMESTAMP WITH TIME ZONE NULL,
 terminal_reason VARCHAR(100) NULL,
 CONSTRAINT ck_verification_job_purpose CHECK
  (purpose IN ('LEAN_CHECK','PYTHON_RUN','CERTIFICATE_GENERATION','CERTIFICATE_VERIFICATION')),
 CONSTRAINT ck_verification_job_state CHECK
  (state IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED','TIMED_OUT')),
 CONSTRAINT ck_verification_job_generation CHECK (current_generation >= 0),
 CONSTRAINT ck_verification_job_event_sequence CHECK (event_sequence >= 0),
 CONSTRAINT ck_verification_job_max_attempts CHECK (max_attempts >= 1),
 CONSTRAINT ck_verification_job_cpu_count CHECK (cpu_count >= 1),
 CONSTRAINT ck_verification_job_cpu_seconds CHECK (cpu_seconds >= 1),
 CONSTRAINT ck_verification_job_wall_seconds CHECK (wall_seconds >= 1),
 CONSTRAINT ck_verification_job_memory_bytes CHECK (memory_bytes >= 1),
 CONSTRAINT ck_verification_job_process_count CHECK (process_count >= 1),
 CONSTRAINT ck_verification_job_disk_bytes CHECK (disk_bytes >= 1),
 CONSTRAINT ck_verification_job_output_bytes CHECK (output_bytes >= 0),
 CONSTRAINT ck_verification_job_log_bytes CHECK (log_bytes >= 0),
 CONSTRAINT ck_verification_job_output_files CHECK (output_files >= 0),
 CONSTRAINT ck_verification_job_manifest_digest CHECK (length(manifest_digest) = 64),
 CONSTRAINT ck_verification_job_request_digest CHECK (length(request_digest) = 64),
 CONSTRAINT ck_verification_job_retry_digest CHECK (length(retry_key_digest) = 64),
 CONSTRAINT ck_verification_job_contract_version CHECK (contract_version >= 1),
 CONSTRAINT uq_verification_job_retry_scope UNIQUE
  (sponsor_user_id, ownership_scope_id, retry_key_digest),
 CONSTRAINT ck_verification_job_terminal_time CHECK (
  (state IN ('QUEUED','RUNNING') AND terminal_at IS NULL) OR
  (state IN ('COMPLETED','FAILED','CANCELLED','TIMED_OUT') AND terminal_at IS NOT NULL))
)
""")
    for column in (
        "ownership_scope_id",
        "sponsor_user_id",
        "work_target_revision_id",
        "research_attempt_revision_id",
        "environment_id",
        "deadline_at",
    ):
        op.execute(f"CREATE INDEX ix_verification_jobs_{column} ON verification_jobs({column})")
    op.execute("CREATE INDEX ix_verification_jobs_queue ON verification_jobs(state, queued_at)")


def _job_members_and_history() -> None:
    op.execute("""
CREATE TABLE verification_inputs (
 job_id UUID NOT NULL REFERENCES verification_jobs(id),
 position INTEGER NOT NULL,
 path VARCHAR(240) NOT NULL,
 role VARCHAR(16) NOT NULL,
 revision_id UUID NULL REFERENCES object_revisions(id),
 artifact_id UUID NULL REFERENCES artifacts(id),
 sha256 VARCHAR(64) NOT NULL,
 PRIMARY KEY (job_id, position),
 CONSTRAINT ck_verification_input_identity CHECK (
  (revision_id IS NOT NULL AND artifact_id IS NULL) OR
  (revision_id IS NULL AND artifact_id IS NOT NULL)),
 CONSTRAINT ck_verification_input_role CHECK (role IN ('SOURCE','INPUT','CERTIFICATE')),
 CONSTRAINT ck_verification_input_position CHECK (position >= 0),
 CONSTRAINT ck_verification_input_digest CHECK (length(sha256) = 64),
 CONSTRAINT uq_verification_input_path UNIQUE (job_id, path)
)
""")
    op.execute(
        "CREATE INDEX ix_verification_inputs_revision_id ON verification_inputs(revision_id)"
    )
    op.execute(
        "CREATE INDEX ix_verification_inputs_artifact_id ON verification_inputs(artifact_id)"
    )
    op.execute("""
CREATE TABLE verification_reservations (
 job_id UUID PRIMARY KEY REFERENCES verification_jobs(id),
 sponsor_user_id UUID NOT NULL REFERENCES users(id),
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 cpu_seconds BIGINT NOT NULL,
 memory_byte_seconds BIGINT NOT NULL,
 disk_bytes BIGINT NOT NULL,
 output_bytes BIGINT NOT NULL,
 state VARCHAR(16) NOT NULL,
 admitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
 released_at TIMESTAMP WITH TIME ZONE NULL,
 accounted_at TIMESTAMP WITH TIME ZONE NULL,
 CONSTRAINT ck_verification_reservation_state CHECK (state IN ('ACTIVE','RELEASED')),
 CONSTRAINT ck_verification_reservation_cpu CHECK (cpu_seconds >= 1),
 CONSTRAINT ck_verification_reservation_memory CHECK (memory_byte_seconds >= 1),
 CONSTRAINT ck_verification_reservation_disk CHECK (disk_bytes >= 1),
 CONSTRAINT ck_verification_reservation_output CHECK (output_bytes >= 0),
 CONSTRAINT ck_verification_reservation_release CHECK (
  (state = 'ACTIVE' AND released_at IS NULL AND accounted_at IS NULL) OR
  (state = 'RELEASED' AND released_at IS NOT NULL))
)
""")
    op.execute(
        "CREATE INDEX ix_verification_reservations_sponsor_user_id "
        "ON verification_reservations(sponsor_user_id)"
    )
    op.execute(
        "CREATE INDEX ix_verification_reservations_ownership_scope_id "
        "ON verification_reservations(ownership_scope_id)"
    )
    op.execute("""
CREATE TABLE verification_attempts (
 id UUID PRIMARY KEY,
 job_id UUID NOT NULL REFERENCES verification_jobs(id),
 generation INTEGER NOT NULL,
 controller_id VARCHAR(200) NOT NULL,
 state VARCHAR(16) NOT NULL,
 lease_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
 started_at TIMESTAMP WITH TIME ZONE NOT NULL,
 terminal_at TIMESTAMP WITH TIME ZONE NULL,
 CONSTRAINT ck_verification_attempt_generation CHECK (generation >= 1),
 CONSTRAINT ck_verification_attempt_state CHECK
  (state IN ('ACTIVE','COMPLETED','FAILED','CANCELLED','TIMED_OUT','LEASE_LOST')),
 CONSTRAINT ck_verification_attempt_terminal_time CHECK (
  (state = 'ACTIVE' AND terminal_at IS NULL) OR
  (state <> 'ACTIVE' AND terminal_at IS NOT NULL)),
 CONSTRAINT uq_verification_attempt_generation UNIQUE (job_id, generation),
 CONSTRAINT uq_verification_attempt_id_job UNIQUE (id, job_id)
)
""")
    op.execute("CREATE INDEX ix_verification_attempts_job_id ON verification_attempts(job_id)")
    op.execute(
        "CREATE INDEX ix_verification_attempts_lease_expires_at "
        "ON verification_attempts(lease_expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_verification_attempts_lease "
        "ON verification_attempts(state, lease_expires_at)"
    )
    op.execute("""
CREATE TABLE verification_events (
 job_id UUID NOT NULL REFERENCES verification_jobs(id),
 sequence INTEGER NOT NULL,
 attempt_id UUID NULL,
 event_type VARCHAR(64) NOT NULL,
 payload JSON NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (job_id, sequence),
 CONSTRAINT ck_verification_event_sequence CHECK (sequence >= 1),
 CONSTRAINT fk_verification_event_attempt_job FOREIGN KEY (attempt_id, job_id)
  REFERENCES verification_attempts(id, job_id)
)
""")
    op.execute("""
CREATE TABLE verification_results (
 id UUID PRIMARY KEY,
 job_id UUID NOT NULL REFERENCES verification_jobs(id),
 attempt_id UUID NOT NULL UNIQUE,
 environment_id UUID NOT NULL REFERENCES verification_environments(id),
 input_manifest_digest VARCHAR(64) NOT NULL,
 outcome VARCHAR(16) NOT NULL,
 diagnostic_summary JSON NOT NULL,
 usage_summary JSON NOT NULL,
 completion_request_digest VARCHAR(64) NOT NULL UNIQUE,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT fk_verification_result_attempt_job FOREIGN KEY (attempt_id, job_id)
  REFERENCES verification_attempts(id, job_id),
 CONSTRAINT ck_verification_result_outcome CHECK
  (outcome IN ('COMPLETED','FAILED','CANCELLED','TIMED_OUT')),
 CONSTRAINT ck_verification_result_completion_digest CHECK
  (length(completion_request_digest) = 64),
 CONSTRAINT ck_verification_result_manifest_digest CHECK
  (length(input_manifest_digest) = 64),
 CONSTRAINT uq_verification_result_binding UNIQUE (id, attempt_id, job_id)
)
""")
    op.execute("CREATE INDEX ix_verification_results_job_id ON verification_results(job_id)")
    op.execute("""
CREATE TABLE verification_output_artifacts (
 attempt_id UUID NOT NULL,
 artifact_id UUID NOT NULL REFERENCES artifacts(id),
 job_id UUID NOT NULL REFERENCES verification_jobs(id),
 result_id UUID NULL REFERENCES verification_results(id),
 path VARCHAR(240) NOT NULL,
 role VARCHAR(16) NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 PRIMARY KEY (attempt_id, artifact_id),
 CONSTRAINT fk_verification_output_attempt_job FOREIGN KEY (attempt_id, job_id)
  REFERENCES verification_attempts(id, job_id),
 CONSTRAINT fk_verification_output_result_binding FOREIGN KEY (result_id, attempt_id, job_id)
  REFERENCES verification_results(id, attempt_id, job_id),
 CONSTRAINT ck_verification_output_role CHECK
  (role IN ('OUTPUT','CERTIFICATE','DIAGNOSTIC')),
 CONSTRAINT uq_verification_output_artifact UNIQUE (artifact_id),
 CONSTRAINT uq_verification_output_path UNIQUE (attempt_id, path)
)
""")
    op.execute(
        "CREATE INDEX ix_verification_output_artifacts_job_id "
        "ON verification_output_artifacts(job_id)"
    )
    op.execute(
        "CREATE INDEX ix_verification_output_artifacts_result_id "
        "ON verification_output_artifacts(result_id)"
    )


def _integrity_triggers() -> None:
    op.execute("""
CREATE FUNCTION protect_verification_environment() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR
  NEW.id IS DISTINCT FROM OLD.id OR
  NEW.language IS DISTINCT FROM OLD.language OR
  NEW.image_digest IS DISTINCT FROM OLD.image_digest OR
  NEW.toolchain_version IS DISTINCT FROM OLD.toolchain_version OR
  NEW.dependency_lock_digest IS DISTINCT FROM OLD.dependency_lock_digest OR
  NEW.build_digest IS DISTINCT FROM OLD.build_digest OR
  NEW.platform_identity IS DISTINCT FROM OLD.platform_identity OR
  NEW.max_cpu_count IS DISTINCT FROM OLD.max_cpu_count OR
  NEW.max_cpu_seconds IS DISTINCT FROM OLD.max_cpu_seconds OR
  NEW.max_wall_seconds IS DISTINCT FROM OLD.max_wall_seconds OR
  NEW.max_memory_bytes IS DISTINCT FROM OLD.max_memory_bytes OR
  NEW.max_process_count IS DISTINCT FROM OLD.max_process_count OR
  NEW.max_disk_bytes IS DISTINCT FROM OLD.max_disk_bytes OR
  NEW.max_output_bytes IS DISTINCT FROM OLD.max_output_bytes OR
  NEW.max_log_bytes IS DISTINCT FROM OLD.max_log_bytes OR
  NEW.max_output_files IS DISTINCT FROM OLD.max_output_files OR
  NEW.created_at IS DISTINCT FROM OLD.created_at
 THEN RAISE EXCEPTION 'verification environment version identity is immutable'; END IF;
 IF NEW.available IS DISTINCT FROM OLD.available THEN
  IF NEW.availability_changed_at <= OLD.availability_changed_at THEN
   RAISE EXCEPTION 'environment availability change requires a later timestamp'; END IF;
 ELSIF NEW.availability_changed_at IS DISTINCT FROM OLD.availability_changed_at THEN
  RAISE EXCEPTION 'availability timestamp changes only with availability';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_environment_identity BEFORE UPDATE OR DELETE
ON verification_environments FOR EACH ROW EXECUTE FUNCTION protect_verification_environment()
""")
    op.execute("""
CREATE FUNCTION validate_verification_job() RETURNS trigger AS $$
DECLARE target_scope uuid; attempt_target uuid;
BEGIN
 SELECT ownership_scope_id INTO target_scope FROM object_revisions
 WHERE id = NEW.work_target_revision_id;
 IF target_scope IS DISTINCT FROM NEW.ownership_scope_id THEN
  RAISE EXCEPTION 'verification target must belong to the owning scope'; END IF;
 IF NEW.research_attempt_revision_id IS NOT NULL THEN
  SELECT target_revision_id INTO attempt_target FROM research_attempt_revisions
  WHERE revision_id = NEW.research_attempt_revision_id;
  IF attempt_target IS DISTINCT FROM NEW.work_target_revision_id THEN
   RAISE EXCEPTION 'research attempt must target the verification work revision'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_job_coherence BEFORE INSERT OR UPDATE
ON verification_jobs FOR EACH ROW EXECUTE FUNCTION validate_verification_job()
""")
    op.execute("""
CREATE FUNCTION protect_verification_job_request() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR
  NEW.id IS DISTINCT FROM OLD.id OR
  NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id OR
  NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id OR
  NEW.contribution_id IS DISTINCT FROM OLD.contribution_id OR
  NEW.work_target_revision_id IS DISTINCT FROM OLD.work_target_revision_id OR
  NEW.research_attempt_revision_id IS DISTINCT FROM OLD.research_attempt_revision_id OR
  NEW.environment_id IS DISTINCT FROM OLD.environment_id OR
  NEW.purpose IS DISTINCT FROM OLD.purpose OR
  NEW.evidence_scope IS DISTINCT FROM OLD.evidence_scope OR
  NEW.entrypoint IS DISTINCT FROM OLD.entrypoint OR
  NEW.arguments::jsonb IS DISTINCT FROM OLD.arguments::jsonb OR
  NEW.seed IS DISTINCT FROM OLD.seed OR
  NEW.manifest_digest IS DISTINCT FROM OLD.manifest_digest OR
  NEW.request_digest IS DISTINCT FROM OLD.request_digest OR
  NEW.retry_key_digest IS DISTINCT FROM OLD.retry_key_digest OR
  NEW.contract_version IS DISTINCT FROM OLD.contract_version OR
  NEW.cpu_count IS DISTINCT FROM OLD.cpu_count OR
  NEW.cpu_seconds IS DISTINCT FROM OLD.cpu_seconds OR
  NEW.wall_seconds IS DISTINCT FROM OLD.wall_seconds OR
  NEW.memory_bytes IS DISTINCT FROM OLD.memory_bytes OR
  NEW.process_count IS DISTINCT FROM OLD.process_count OR
  NEW.disk_bytes IS DISTINCT FROM OLD.disk_bytes OR
  NEW.output_bytes IS DISTINCT FROM OLD.output_bytes OR
  NEW.log_bytes IS DISTINCT FROM OLD.log_bytes OR
  NEW.output_files IS DISTINCT FROM OLD.output_files OR
  NEW.max_attempts IS DISTINCT FROM OLD.max_attempts OR
  NEW.queued_at IS DISTINCT FROM OLD.queued_at OR
  NEW.deadline_at IS DISTINCT FROM OLD.deadline_at
 THEN RAISE EXCEPTION 'verification job request is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_job_request_immutable BEFORE UPDATE OR DELETE
ON verification_jobs FOR EACH ROW EXECUTE FUNCTION protect_verification_job_request()
""")
    op.execute("""
CREATE FUNCTION protect_verification_job_lifecycle() RETURNS trigger AS $$
BEGIN
 IF OLD.state IN ('COMPLETED','FAILED','CANCELLED','TIMED_OUT') THEN
  RAISE EXCEPTION 'terminal verification job is immutable'; END IF;
 IF NEW.current_generation < OLD.current_generation OR
  NEW.current_generation > NEW.max_attempts OR
  NEW.event_sequence < OLD.event_sequence THEN
  RAISE EXCEPTION 'verification job counters must advance within admitted bounds'; END IF;
 IF OLD.state = 'QUEUED' AND NEW.state NOT IN
  ('QUEUED','RUNNING','FAILED','CANCELLED','TIMED_OUT') THEN
  RAISE EXCEPTION 'invalid queued verification transition'; END IF;
 IF OLD.state = 'RUNNING' AND NEW.state NOT IN
  ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED','TIMED_OUT') THEN
  RAISE EXCEPTION 'invalid running verification transition'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_job_lifecycle BEFORE UPDATE
ON verification_jobs FOR EACH ROW EXECUTE FUNCTION protect_verification_job_lifecycle()
""")
    op.execute("""
CREATE FUNCTION validate_verification_input() RETURNS trigger AS $$
DECLARE artifact_state varchar(16);
BEGIN
 IF NEW.artifact_id IS NOT NULL THEN
  SELECT state INTO artifact_state FROM artifacts WHERE id = NEW.artifact_id FOR SHARE;
  IF artifact_state <> 'COMMITTED' THEN
   RAISE EXCEPTION 'verification inputs require committed artifacts'; END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_input_valid BEFORE INSERT ON verification_inputs
FOR EACH ROW EXECUTE FUNCTION validate_verification_input()
""")
    op.execute("""
CREATE FUNCTION protect_verification_attempt() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR
  NEW.id IS DISTINCT FROM OLD.id OR NEW.job_id IS DISTINCT FROM OLD.job_id OR
  NEW.generation IS DISTINCT FROM OLD.generation OR
  NEW.controller_id IS DISTINCT FROM OLD.controller_id OR
  NEW.started_at IS DISTINCT FROM OLD.started_at
 THEN RAISE EXCEPTION 'verification attempt identity is immutable'; END IF;
 IF OLD.state = 'ACTIVE' AND NEW.state = 'ACTIVE' THEN
  IF NEW.lease_expires_at < OLD.lease_expires_at THEN
   RAISE EXCEPTION 'verification lease cannot move backward'; END IF;
 ELSIF OLD.state = 'ACTIVE' AND NEW.state <> 'ACTIVE' THEN NULL;
 ELSE RAISE EXCEPTION 'terminal verification attempt is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_attempt_lifecycle BEFORE UPDATE OR DELETE
ON verification_attempts FOR EACH ROW EXECUTE FUNCTION protect_verification_attempt()
""")
    op.execute("""
CREATE FUNCTION protect_verification_reservation() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR
  NEW.job_id IS DISTINCT FROM OLD.job_id OR
  NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id OR
  NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id OR
  NEW.cpu_seconds IS DISTINCT FROM OLD.cpu_seconds OR
  NEW.memory_byte_seconds IS DISTINCT FROM OLD.memory_byte_seconds OR
  NEW.disk_bytes IS DISTINCT FROM OLD.disk_bytes OR
  NEW.output_bytes IS DISTINCT FROM OLD.output_bytes OR
  NEW.admitted_at IS DISTINCT FROM OLD.admitted_at
 THEN RAISE EXCEPTION 'verification reservation identity is immutable'; END IF;
 IF OLD.state = 'ACTIVE' AND NEW.state = 'RELEASED' THEN NULL;
 ELSIF OLD.state = NEW.state AND OLD.released_at IS NOT DISTINCT FROM NEW.released_at AND
  (OLD.accounted_at IS NULL OR OLD.accounted_at IS NOT DISTINCT FROM NEW.accounted_at)
 THEN NULL;
 ELSE RAISE EXCEPTION 'verification reservation can be released and accounted only once'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_reservation_lifecycle BEFORE UPDATE OR DELETE
ON verification_reservations FOR EACH ROW EXECUTE FUNCTION protect_verification_reservation()
""")
    op.execute("""
CREATE FUNCTION validate_verification_output() RETURNS trigger AS $$
DECLARE artifact_scope uuid; artifact_state varchar(16); job_scope uuid;
BEGIN
 SELECT ownership_scope_id, state INTO artifact_scope, artifact_state
 FROM artifacts WHERE id = NEW.artifact_id FOR SHARE;
 SELECT ownership_scope_id INTO job_scope FROM verification_jobs WHERE id = NEW.job_id;
 IF artifact_state <> 'STAGING' THEN
  RAISE EXCEPTION 'verification outputs must bind staged artifacts'; END IF;
 IF artifact_scope IS DISTINCT FROM job_scope THEN
  RAISE EXCEPTION 'verification output artifact must belong to the job scope'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_output_valid BEFORE INSERT ON verification_output_artifacts
FOR EACH ROW EXECUTE FUNCTION validate_verification_output()
""")
    for table in (
        "verification_inputs",
        "verification_events",
        "verification_results",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION protect_verification_output() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR
  NEW.attempt_id IS DISTINCT FROM OLD.attempt_id OR
  NEW.artifact_id IS DISTINCT FROM OLD.artifact_id OR
  NEW.job_id IS DISTINCT FROM OLD.job_id OR
  NEW.path IS DISTINCT FROM OLD.path OR
  NEW.role IS DISTINCT FROM OLD.role OR
  NEW.created_at IS DISTINCT FROM OLD.created_at OR
  OLD.result_id IS NOT NULL OR NEW.result_id IS NULL
 THEN RAISE EXCEPTION 'verification output binding is immutable after completion'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER verification_output_immutable BEFORE UPDATE OR DELETE
ON verification_output_artifacts FOR EACH ROW EXECUTE FUNCTION protect_verification_output()
""")


def downgrade() -> None:
    raise RuntimeError("Verification job identity and history are durable; do not discard them.")

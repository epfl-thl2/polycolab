"""Add typed exact artifacts to immutable agent context manifests."""

from alembic import op

revision = "20260908_context_artifacts"
down_revision = "20260907_computation_kinds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE agent_runs
ADD COLUMN requested_context_artifact_ids JSON NOT NULL DEFAULT '[]'::json
""")
    op.execute("""
ALTER TABLE context_manifests
ADD COLUMN artifact_ids JSON NOT NULL DEFAULT '[]'::json
""")
    op.execute("""
CREATE TABLE context_manifest_artifacts (
 manifest_id UUID NOT NULL REFERENCES context_manifests(id),
 artifact_id UUID NOT NULL REFERENCES artifacts(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, artifact_id),
 CONSTRAINT ck_context_manifest_artifact_position CHECK (position >= 0),
 CONSTRAINT uq_context_manifest_artifact_position UNIQUE (manifest_id, position)
)
""")
    op.execute("""
CREATE INDEX ix_context_manifest_artifacts_artifact_id
ON context_manifest_artifacts(artifact_id)
""")
    op.execute("""
CREATE FUNCTION validate_context_manifest_artifact() RETURNS trigger AS $$
DECLARE
 expected_id TEXT;
 manifest_project UUID;
 artifact_project UUID;
 artifact_state VARCHAR(16);
BEGIN
 SELECT cm.artifact_ids ->> NEW.position, cm.project_id, rs.project_id, a.state
 INTO expected_id, manifest_project, artifact_project, artifact_state
 FROM context_manifests cm
 JOIN artifacts a ON a.id = NEW.artifact_id
 JOIN research_scopes rs ON rs.id = a.ownership_scope_id
 WHERE cm.id = NEW.manifest_id;
 IF expected_id IS DISTINCT FROM NEW.artifact_id::text
    OR artifact_project IS DISTINCT FROM manifest_project
    OR artifact_state <> 'COMMITTED' THEN
  RAISE EXCEPTION 'context manifest artifact mismatch';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER context_manifest_artifact_scope
BEFORE INSERT ON context_manifest_artifacts
FOR EACH ROW EXECUTE FUNCTION validate_context_manifest_artifact()
""")
    op.execute("""
CREATE FUNCTION validate_context_manifest_artifact_set() RETURNS trigger AS $$
DECLARE member_count INTEGER;
BEGIN
 IF json_typeof(NEW.artifact_ids) <> 'array'
    OR json_array_length(NEW.artifact_ids) > 32 THEN
  RAISE EXCEPTION 'invalid context manifest artifact set';
 END IF;
 SELECT count(*) INTO member_count
 FROM context_manifest_artifacts WHERE manifest_id = NEW.id;
 IF member_count <> json_array_length(NEW.artifact_ids) THEN
  RAISE EXCEPTION 'incomplete context manifest artifact set';
 END IF;
 RETURN NULL;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER context_manifest_artifact_set
AFTER INSERT ON context_manifests DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION validate_context_manifest_artifact_set()
""")
    op.execute("""
CREATE TRIGGER context_manifest_artifacts_immutable
BEFORE UPDATE OR DELETE ON context_manifest_artifacts
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")


def downgrade() -> None:
    raise RuntimeError("Exact agent context artifact history is durable.")

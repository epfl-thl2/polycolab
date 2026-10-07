"""Shared scoped artifact identity and typed research/publication bindings."""

from alembic import op

revision = "20260907_artifact_foundation"
down_revision = "20260907_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _artifact_table()
    _binding_tables()
    _integrity_triggers()


def _artifact_table() -> None:
    op.execute("""
CREATE TABLE artifacts (
 id UUID PRIMARY KEY,
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 sha256 VARCHAR(64) NOT NULL,
 byte_length BIGINT NOT NULL,
 media_type VARCHAR(127) NOT NULL,
 storage_key VARCHAR(500) NOT NULL UNIQUE,
 source_revision_id UUID NULL REFERENCES object_revisions(id),
 environment JSON NULL,
 state VARCHAR(16) NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
 verified_at TIMESTAMP WITH TIME ZONE NULL,
 committed_at TIMESTAMP WITH TIME ZONE NULL,
 deleted_at TIMESTAMP WITH TIME ZONE NULL,
 CONSTRAINT uq_artifacts_id_scope UNIQUE (id, ownership_scope_id),
 CONSTRAINT ck_artifacts_sha256_length CHECK (length(sha256) = 64),
 CONSTRAINT ck_artifacts_byte_length CHECK (byte_length >= 0),
 CONSTRAINT ck_artifacts_state CHECK
  (state IN ('STAGING','COMMITTED','DELETING','DELETED')),
 CONSTRAINT ck_artifacts_lifecycle CHECK (
  (state = 'STAGING' AND committed_at IS NULL AND deleted_at IS NULL) OR
  (state = 'COMMITTED' AND verified_at IS NOT NULL AND committed_at IS NOT NULL
   AND deleted_at IS NULL) OR
  (state = 'DELETING' AND committed_at IS NULL AND deleted_at IS NULL) OR
  (state = 'DELETED' AND committed_at IS NULL AND deleted_at IS NOT NULL))
)
""")
    for column in ("ownership_scope_id", "created_by_user_id", "sha256", "expires_at"):
        op.execute(f"CREATE INDEX ix_artifacts_{column} ON artifacts({column})")


def _binding_tables() -> None:
    op.execute("""
CREATE TABLE artifact_research_links (
 id UUID PRIMARY KEY,
 artifact_id UUID NOT NULL REFERENCES artifacts(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 attempt_revision_id UUID NULL REFERENCES research_attempt_revisions(revision_id),
 role VARCHAR(32) NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT ck_artifact_research_role CHECK
  (role IN ('SOURCE','INPUT','EVIDENCE','OUTPUT','FORMALIZATION','CERTIFICATE')),
 CONSTRAINT uq_artifact_research_binding UNIQUE
  (artifact_id, revision_id, attempt_revision_id, role)
)
""")
    for column in (
        "artifact_id",
        "revision_id",
        "attempt_revision_id",
        "created_by_user_id",
    ):
        op.execute(
            f"CREATE INDEX ix_artifact_research_links_{column} ON artifact_research_links({column})"
        )
    op.execute("""
CREATE TABLE publication_artifact_members (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 artifact_id UUID NOT NULL REFERENCES artifacts(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, artifact_id),
 CONSTRAINT uq_publication_artifact_position UNIQUE (manifest_id, position)
)
""")


def _integrity_triggers() -> None:
    op.execute("""
CREATE FUNCTION protect_artifact_identity() RETURNS trigger AS $$
BEGIN
IF TG_OP = 'DELETE' OR
 NEW.id IS DISTINCT FROM OLD.id OR
 NEW.ownership_scope_id IS DISTINCT FROM OLD.ownership_scope_id OR
 NEW.contribution_id IS DISTINCT FROM OLD.contribution_id OR
 NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id OR
 NEW.sha256 IS DISTINCT FROM OLD.sha256 OR
 NEW.byte_length IS DISTINCT FROM OLD.byte_length OR
 NEW.media_type IS DISTINCT FROM OLD.media_type OR
 NEW.storage_key IS DISTINCT FROM OLD.storage_key OR
 NEW.source_revision_id IS DISTINCT FROM OLD.source_revision_id OR
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
CREATE TRIGGER artifacts_identity_lifecycle BEFORE UPDATE OR DELETE ON artifacts
FOR EACH ROW EXECUTE FUNCTION protect_artifact_identity()
""")
    for table in ("artifact_research_links", "publication_artifact_members"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION validate_artifact_research_link() RETURNS trigger AS $$
DECLARE artifact_scope uuid; artifact_state varchar(16); target_scope uuid;
BEGIN
 SELECT ownership_scope_id, state INTO artifact_scope, artifact_state
 FROM artifacts WHERE id = NEW.artifact_id FOR SHARE;
 SELECT ownership_scope_id INTO target_scope FROM object_revisions WHERE id = NEW.revision_id;
 IF artifact_state <> 'COMMITTED' THEN
  RAISE EXCEPTION 'only committed artifacts may be attached';
 END IF;
 IF artifact_scope IS DISTINCT FROM target_scope AND NOT EXISTS
  (SELECT 1 FROM public_releases WHERE object_revision_id = NEW.revision_id) THEN
  RAISE EXCEPTION 'cross-scope artifact links require an exact public release';
 END IF;
 RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER artifact_research_link_valid BEFORE INSERT ON artifact_research_links
FOR EACH ROW EXECUTE FUNCTION validate_artifact_research_link()
""")
    op.execute("""
CREATE FUNCTION validate_publication_artifact_member() RETURNS trigger AS $$
DECLARE artifact_state varchar(16);
BEGIN
 SELECT state INTO artifact_state FROM artifacts WHERE id = NEW.artifact_id FOR SHARE;
 IF artifact_state <> 'COMMITTED' THEN
  RAISE EXCEPTION 'only committed artifacts may be published';
 END IF;
 IF NOT EXISTS (
  SELECT 1 FROM artifact_research_links link
  JOIN publication_revisions member ON member.revision_id = link.revision_id
  WHERE link.artifact_id = NEW.artifact_id AND member.manifest_id = NEW.manifest_id
 ) THEN RAISE EXCEPTION 'published artifact requires a released research binding'; END IF;
 RETURN NEW; END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER publication_artifact_member_valid BEFORE INSERT ON publication_artifact_members
FOR EACH ROW EXECUTE FUNCTION validate_publication_artifact_member()
""")


def downgrade() -> None:
    raise RuntimeError("Artifact identity and bindings are durable; do not discard them.")

"""Human catalogue admission, official source history, and moderation.

Revision ID: 20260906_catalogue
Revises: 20260905_baseline
"""

from alembic import op

revision = "20260906_catalogue"
down_revision = "20260905_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE catalogue_entries (
 id UUID PRIMARY KEY REFERENCES research_objects(id),
 official_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 admitted_by_user_id UUID NOT NULL REFERENCES users(id),
 hidden BOOLEAN NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT fk_catalogue_official_object FOREIGN KEY (official_revision_id, id)
 REFERENCES object_revisions(id, object_id)
)
""")
    op.execute("CREATE INDEX ix_catalogue_visible_id ON catalogue_entries(hidden, id)")
    op.execute("""
CREATE TABLE catalogue_revisions (
 revision_id UUID PRIMARY KEY REFERENCES statement_revisions(revision_id),
 entry_id UUID NOT NULL REFERENCES catalogue_entries(id),
 source_identifier VARCHAR(2000) NOT NULL,
 source_version VARCHAR(500) NOT NULL,
 source_locator VARCHAR(1000) NOT NULL,
 reported_status VARCHAR(200) NOT NULL,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 CONSTRAINT fk_catalogue_revision_object FOREIGN KEY (revision_id, entry_id)
 REFERENCES object_revisions(id, object_id)
)
""")
    op.execute("CREATE INDEX ix_catalogue_revisions_entry_id ON catalogue_revisions(entry_id)")
    op.execute("""
CREATE TABLE catalogue_audit (
 id UUID PRIMARY KEY,
 entry_id UUID NOT NULL REFERENCES catalogue_entries(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 action VARCHAR(16) NOT NULL,
 reason TEXT NOT NULL,
 actor_user_id UUID NOT NULL REFERENCES users(id),
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_catalogue_audit_action CHECK
 (action IN ('ADMIT','PROMOTE','REVISE','HIDE','RESTORE')),
 CONSTRAINT fk_catalogue_audit_revision FOREIGN KEY (revision_id, entry_id)
 REFERENCES object_revisions(id, object_id)
)
""")
    op.execute("CREATE INDEX ix_catalogue_audit_entry_id ON catalogue_audit(entry_id)")
    op.execute("""
CREATE TABLE catalogue_moderators (
 user_id UUID PRIMARY KEY REFERENCES users(id), active BOOLEAN NOT NULL
)
""")
    op.execute("""
CREATE TABLE catalogue_moderator_audit (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id),
 operator_user_id UUID NOT NULL REFERENCES users(id),
 active BOOLEAN NOT NULL,
 reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
)
""")
    op.execute(
        "CREATE INDEX ix_catalogue_moderator_audit_user_id ON catalogue_moderator_audit(user_id)"
    )
    for table in ("catalogue_revisions", "catalogue_audit", "catalogue_moderator_audit"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION protect_catalogue_identity() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' OR NEW.id IS DISTINCT FROM OLD.id
 OR NEW.admitted_by_user_id IS DISTINCT FROM OLD.admitted_by_user_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
  RAISE EXCEPTION 'immutable catalogue identity';
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER catalogue_identity BEFORE UPDATE OR DELETE ON catalogue_entries
FOR EACH ROW EXECUTE FUNCTION protect_catalogue_identity()
""")
    op.execute("""
CREATE FUNCTION validate_catalogue_entry() RETURNS trigger AS $$
DECLARE entry catalogue_entries%ROWTYPE;
BEGIN
 SELECT * INTO entry FROM catalogue_entries WHERE id=NEW.id;
 IF NOT EXISTS (
  SELECT 1 FROM research_objects obj JOIN research_scopes scope ON scope.id=obj.ownership_scope_id
  WHERE obj.id=entry.id AND scope.scope_kind='COMMONS' AND obj.entity_class='STATEMENT'
 ) OR NOT EXISTS (
  SELECT 1 FROM catalogue_revisions WHERE entry_id=entry.id
  AND revision_id=entry.official_revision_id
 ) OR NOT EXISTS (
  SELECT 1 FROM public_releases WHERE object_revision_id=entry.official_revision_id
 ) THEN RAISE EXCEPTION 'incomplete catalogue admission'; END IF;
 RETURN NULL;
END; $$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE CONSTRAINT TRIGGER catalogue_complete AFTER INSERT OR UPDATE ON catalogue_entries
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION validate_catalogue_entry()
""")
    op.execute("""
CREATE FUNCTION validate_catalogue_contribution() RETURNS trigger AS $$
DECLARE actor_id uuid;
BEGIN
 SELECT human_user_id INTO actor_id FROM contribution_envelopes envelope
 JOIN research_objects obj ON obj.id=NEW.entry_id
 WHERE envelope.id=NEW.contribution_id AND envelope.actor_kind='HUMAN'
 AND envelope.ownership_scope_id=obj.ownership_scope_id;
 IF actor_id IS NULL THEN RAISE EXCEPTION 'invalid catalogue contribution'; END IF;
 IF TG_TABLE_NAME='catalogue_audit' THEN
  IF NEW.actor_user_id IS DISTINCT FROM actor_id THEN
   RAISE EXCEPTION 'catalogue audit actor mismatch';
  END IF;
 END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql
""")
    for table in ("catalogue_revisions", "catalogue_audit"):
        op.execute(
            f"CREATE TRIGGER {table}_contribution BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION validate_catalogue_contribution()"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Catalogue history must be retained; disable the cohort instead of downgrading."
    )

"""Immutable private workspace pins with explicit version upgrades."""

from alembic import op

revision = "20260906_references"
down_revision = "20260906_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE workspace_references (
 id UUID PRIMARY KEY,
 project_id UUID NOT NULL REFERENCES projects(id),
 object_id UUID NOT NULL REFERENCES research_objects(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_workspace_reference_target UNIQUE (project_id, object_id)
)
""")
    op.execute(
        "CREATE INDEX ix_workspace_references_project_id ON workspace_references(project_id)"
    )
    op.execute("""
CREATE TABLE workspace_reference_versions (
 id UUID PRIMARY KEY,
 reference_id UUID NOT NULL REFERENCES workspace_references(id),
 number INTEGER NOT NULL,
 base_version_id UUID REFERENCES workspace_reference_versions(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_workspace_reference_number UNIQUE (reference_id, number),
 CONSTRAINT ck_workspace_reference_number CHECK (number > 0)
)
""")
    for table in ("workspace_references", "workspace_reference_versions"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE FUNCTION validate_workspace_reference_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target UUID; previous workspace_reference_versions;
BEGIN
 SELECT object_id INTO target FROM workspace_references WHERE id = NEW.reference_id FOR UPDATE;
 IF NOT EXISTS (SELECT 1 FROM object_revisions
                WHERE id = NEW.revision_id AND object_id = target)
 THEN RAISE EXCEPTION 'reference target identity mismatch'; END IF;
 SELECT * INTO previous FROM workspace_reference_versions
 WHERE reference_id = NEW.reference_id ORDER BY number DESC LIMIT 1;
 IF previous.id IS NULL THEN
   IF NEW.number <> 1 OR NEW.base_version_id IS NOT NULL
   THEN RAISE EXCEPTION 'invalid initial reference'; END IF;
 ELSE
   IF NEW.number <> previous.number + 1 OR NEW.base_version_id IS DISTINCT FROM previous.id
   THEN RAISE EXCEPTION 'stale reference base'; END IF;
 END IF;
 RETURN NEW;
END $$
""")
    op.execute("""
CREATE TRIGGER workspace_reference_version_insert BEFORE INSERT ON workspace_reference_versions
FOR EACH ROW EXECUTE FUNCTION validate_workspace_reference_version()
""")


def downgrade() -> None:
    raise RuntimeError("Retain private reference history; disable writes instead of dropping pins.")

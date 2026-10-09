"""Typed attached research and public visibility ancestry."""

from alembic import op

revision = "20260906_records"
down_revision = "20260906_catalogue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_objects DROP CONSTRAINT ck_research_objects_kind")
    op.execute("""
ALTER TABLE research_objects ADD CONSTRAINT ck_research_objects_kind CHECK
(kind IN ('PROBLEM','DEFINITION','CLAIM','PROOF','ATTEMPT','COUNTEREXAMPLE',
'NOTE','IDEA','DISCUSSION'))
""")
    op.execute("""
CREATE TABLE research_attachments (
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 statement_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 PRIMARY KEY (revision_id, statement_revision_id)
)
""")
    op.execute("""
CREATE INDEX ix_research_attachments_statement_revision_id
ON research_attachments(statement_revision_id)
""")
    op.execute("""
CREATE TABLE public_research_anchors (
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 entry_id UUID NOT NULL REFERENCES catalogue_entries(id),
 PRIMARY KEY (revision_id, entry_id)
)
""")
    for table in ("research_attachments", "public_research_anchors"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_insert_boundary BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_revision_extension()"
        )


def downgrade() -> None:
    raise RuntimeError("Retain research history; disable new writes instead of dropping records.")

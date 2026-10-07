"""Audited record-level moderation independent of catalogue admission."""

from alembic import op

revision = "20260906_moderation"
down_revision = "20260906_community"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE record_moderation (
 object_id UUID PRIMARY KEY REFERENCES research_objects(id),
 hidden BOOLEAN NOT NULL
)
""")
    op.execute("""
CREATE TABLE record_moderation_audit (
 id UUID PRIMARY KEY,
 object_id UUID NOT NULL REFERENCES research_objects(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 actor_user_id UUID NOT NULL REFERENCES users(id),
 hidden BOOLEAN NOT NULL,
 reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
)
""")
    op.execute(
        "CREATE INDEX ix_record_moderation_audit_object_id ON record_moderation_audit(object_id)"
    )
    op.execute("""
CREATE TRIGGER record_moderation_audit_immutable BEFORE UPDATE OR DELETE ON record_moderation_audit
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")


def downgrade() -> None:
    raise RuntimeError("Retain moderation decisions and visibility state.")

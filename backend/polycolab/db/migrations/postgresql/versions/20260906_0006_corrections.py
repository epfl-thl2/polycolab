"""Public correction submissions and immutable human decisions."""

from alembic import op

revision = "20260906_corrections"
down_revision = "20260906_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE correction_suggestions (
 revision_id UUID PRIMARY KEY REFERENCES object_revisions(id),
 target_revision_id UUID NOT NULL REFERENCES statement_revisions(revision_id),
 proposed JSON NOT NULL
)
""")
    op.execute("""
CREATE TABLE correction_decisions (
 suggestion_revision_id UUID PRIMARY KEY REFERENCES correction_suggestions(revision_id),
 action VARCHAR(32) NOT NULL,
 decided_by_user_id UUID NOT NULL REFERENCES users(id),
 decided_revision_id UUID REFERENCES object_revisions(id),
 request_digest VARCHAR(64) NOT NULL,
 reason TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL
)
""")
    for table in ("correction_suggestions", "correction_decisions"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )
    op.execute("""
CREATE TRIGGER correction_suggestion_insert BEFORE INSERT ON correction_suggestions
FOR EACH ROW EXECUTE FUNCTION protect_revision_extension()
""")


def downgrade() -> None:
    raise RuntimeError("Retain submitted corrections and decisions; disable new writes instead.")

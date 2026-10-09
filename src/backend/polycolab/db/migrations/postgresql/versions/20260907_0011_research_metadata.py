"""Retain assumptions and reported research outcomes for every research kind."""

from alembic import op

revision = "20260907_research_metadata"
down_revision = "20260906_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing unknown assumptions stay unknown; never invent historical content.
    op.execute("ALTER TABLE record_revisions ADD COLUMN assumptions_md TEXT NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE record_revisions ALTER COLUMN assumptions_md DROP DEFAULT")
    op.execute("ALTER TABLE statement_revisions ADD COLUMN reported_outcome VARCHAR(64)")
    op.execute("ALTER TABLE statement_revisions ADD COLUMN explanation_md TEXT")


def downgrade() -> None:
    raise RuntimeError("Research metadata is immutable history; do not discard it.")

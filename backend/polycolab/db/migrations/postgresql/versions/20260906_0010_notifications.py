"""Resumable community fan-out and rebuildable bounded summary snapshots."""

from alembic import op

revision = "20260906_notifications"
down_revision = "20260906_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE community_delivery_cursors (
 event_id UUID PRIMARY KEY REFERENCES outbox_events(id),
 entry_id UUID REFERENCES catalogue_entries(id),
 user_id UUID REFERENCES users(id),
 done BOOLEAN NOT NULL
)
""")
    op.execute("""
CREATE TABLE research_notifications (
 id UUID PRIMARY KEY,
 user_id UUID NOT NULL REFERENCES users(id),
 event_id UUID NOT NULL REFERENCES outbox_events(id),
 entry_id UUID NOT NULL REFERENCES catalogue_entries(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_research_notification_delivery UNIQUE (user_id, event_id, entry_id)
)
""")
    op.execute("CREATE INDEX ix_research_notifications_user_id ON research_notifications(user_id)")
    op.execute("""
CREATE TABLE research_progress_summaries (
 entry_id UUID PRIMARY KEY REFERENCES catalogue_entries(id),
 revision_ids JSON NOT NULL,
 inputs_digest VARCHAR(64) NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL
)
""")


def downgrade() -> None:
    raise RuntimeError("Retain notification delivery history; derived summaries can be rebuilt.")

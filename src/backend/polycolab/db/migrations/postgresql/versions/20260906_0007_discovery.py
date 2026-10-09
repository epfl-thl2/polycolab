"""PostgreSQL full-text indexes for exact research and source metadata."""

from alembic import op

revision = "20260906_discovery"
down_revision = "20260906_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE INDEX ix_record_explanation_search ON record_revisions USING gin
(to_tsvector('simple', coalesce(explanation_md, '')))
""")
    op.execute("""
CREATE INDEX ix_revision_search ON object_revisions USING gin
(to_tsvector('simple', title || ' ' || content_md))
""")
    op.execute("""
CREATE INDEX ix_catalogue_source_search ON catalogue_revisions USING gin
(to_tsvector('simple', source_identifier || ' ' || source_version || ' ' || source_locator))
""")


def downgrade() -> None:
    op.drop_index("ix_record_explanation_search", table_name="record_revisions")
    op.drop_index("ix_catalogue_source_search", table_name="catalogue_revisions")
    op.drop_index("ix_revision_search", table_name="object_revisions")

"""Selective publication manifests and exact optional members."""

from alembic import op

revision = "20260907_publication"
down_revision = "20260907_proofs_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE publication_manifests (
 id UUID PRIMARY KEY,
 project_id UUID NOT NULL REFERENCES projects(id),
 ownership_scope_id UUID NOT NULL REFERENCES research_scopes(id),
 preview_digest VARCHAR(64) NOT NULL UNIQUE,
 contribution_id UUID NOT NULL REFERENCES contribution_envelopes(id),
 created_by_user_id UUID NOT NULL REFERENCES users(id),
 selection JSON NOT NULL,
 public_fields JSON NOT NULL,
 created_at TIMESTAMP WITH TIME ZONE NOT NULL,
 CONSTRAINT fk_publication_manifest_workspace_scope FOREIGN KEY
  (ownership_scope_id, project_id) REFERENCES research_scopes(id, project_id),
 CONSTRAINT ck_publication_preview_digest CHECK (length(preview_digest) = 64)
)
""")
    op.execute(
        "CREATE INDEX ix_publication_manifests_project_id ON publication_manifests(project_id)"
    )
    op.execute(
        "CREATE INDEX ix_publication_manifests_ownership_scope_id "
        "ON publication_manifests(ownership_scope_id)"
    )
    op.execute("ALTER TABLE public_releases ADD COLUMN publication_manifest_id UUID NULL")
    op.execute(
        "ALTER TABLE public_releases ADD CONSTRAINT fk_public_releases_publication_manifest_id "
        "FOREIGN KEY(publication_manifest_id) REFERENCES publication_manifests(id)"
    )
    op.execute(
        "CREATE INDEX ix_public_releases_publication_manifest_id "
        "ON public_releases(publication_manifest_id)"
    )
    _member_tables()
    for table in (
        "publication_manifests",
        "publication_revisions",
        "publication_summaries",
        "publication_comments",
        "publication_progress",
        "publication_relations",
    ):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
        )


def _member_tables() -> None:
    op.execute("""
CREATE TABLE publication_revisions (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 revision_id UUID NOT NULL REFERENCES object_revisions(id),
 position INTEGER NOT NULL,
 selected BOOLEAN NOT NULL,
 PRIMARY KEY (manifest_id, revision_id),
 CONSTRAINT uq_publication_revision_position UNIQUE (manifest_id, position)
)
""")
    op.execute("""
CREATE TABLE publication_summaries (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 summary_revision_id UUID NOT NULL REFERENCES research_summary_revisions(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, summary_revision_id),
 CONSTRAINT uq_publication_summary_position UNIQUE (manifest_id, position)
)
""")
    op.execute("""
CREATE TABLE publication_comments (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 comment_id UUID NOT NULL REFERENCES research_comments(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, comment_id),
 CONSTRAINT uq_publication_comment_position UNIQUE (manifest_id, position)
)
""")
    op.execute("""
CREATE TABLE publication_progress (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 progress_id UUID NOT NULL REFERENCES research_progress_updates(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, progress_id),
 CONSTRAINT uq_publication_progress_position UNIQUE (manifest_id, position)
)
""")
    op.execute("""
CREATE TABLE publication_relations (
 manifest_id UUID NOT NULL REFERENCES publication_manifests(id),
 relation_id UUID NOT NULL REFERENCES relation_assertions(id),
 position INTEGER NOT NULL,
 PRIMARY KEY (manifest_id, relation_id),
 CONSTRAINT uq_publication_relation_position UNIQUE (manifest_id, position)
)
""")


def downgrade() -> None:
    raise RuntimeError("Publication history is immutable; do not discard it.")

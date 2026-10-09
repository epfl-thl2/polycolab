"""Canonical kind index and version metadata for local databases."""

import sqlalchemy as sa
from alembic import op

revision = "local_20260918_object_semantics"
down_revision = "local_20260917_custom_agents"
branch_labels = None
depends_on = None

KIND_SQL = (
    "CASE kind WHEN 'CLAIM' THEN 'STATEMENT' WHEN 'PROOF_SKETCH' THEN 'PROOF' "
    "WHEN 'IDEA' THEN 'NOTE' WHEN 'DISCUSSION' THEN 'NOTE' "
    "WHEN 'COUNTEREXAMPLE' THEN 'NOTE' WHEN 'COMPUTATION' THEN 'NOTE' ELSE kind END"
)


def upgrade() -> None:
    # SQLite permits adding a VIRTUAL generated column without rebuilding the
    # immutable research tables or their triggers.
    op.add_column(
        "research_objects",
        sa.Column("canonical_kind", sa.String(32), sa.Computed(KIND_SQL), nullable=False),
    )
    op.create_index("ix_research_objects_canonical_kind", "research_objects", ["canonical_kind"])
    op.add_column(
        "object_revisions",
        sa.Column("semantic_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )

    op.add_column(
        "external_agent_credentials",
        sa.Column("allow_reviews", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "object_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "object_version_id", sa.Uuid(), sa.ForeignKey("object_revisions.id"), nullable=False
        ),
        sa.Column(
            "ownership_scope_id", sa.Uuid(), sa.ForeignKey("research_scopes.id"), nullable=False
        ),
        sa.Column(
            "contribution_id", sa.Uuid(), sa.ForeignKey("contribution_envelopes.id"), nullable=False
        ),
        sa.Column("reviewer_id", sa.String(200), nullable=False),
        sa.Column("actor_kind", sa.String(16), nullable=False),
        sa.Column("reviewer_name", sa.String(500), nullable=False),
        sa.Column("model_id", sa.String(500)),
        sa.Column("outcome", sa.String(32)),
        sa.Column("scope", sa.String(1000), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_object_version_ids", sa.JSON(), nullable=False),
        sa.Column("withdrawn", sa.Boolean(), nullable=False),
        sa.Column("self_review", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("actor_kind IN ('HUMAN', 'AGENT')", name="ck_object_reviews_actor"),
        sa.CheckConstraint(
            "(withdrawn AND outcome IS NULL) OR (NOT withdrawn AND outcome IS NOT NULL "
            "AND outcome IN ('SUPPORTS', 'ISSUES_FOUND', 'INCONCLUSIVE'))",
            name="ck_object_reviews_outcome",
        ),
    )
    op.create_index(
        "ix_object_reviews_current",
        "object_reviews",
        ["object_version_id", "reviewer_id", "created_at", "id"],
    )
    op.create_index(
        "ix_object_reviews_ownership_scope_id", "object_reviews", ["ownership_scope_id"]
    )
    op.create_index("ix_object_reviews_contribution_id", "object_reviews", ["contribution_id"])
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER object_reviews_no_{operation.lower()} BEFORE {operation} "
            "ON object_reviews BEGIN SELECT RAISE(ABORT, 'reviews are immutable'); END"
        )

    op.create_table(
        "review_evidence",
        sa.Column("review_id", sa.Uuid(), sa.ForeignKey("object_reviews.id"), primary_key=True),
        sa.Column(
            "object_version_id", sa.Uuid(), sa.ForeignKey("object_revisions.id"), primary_key=True
        ),
    )
    op.create_table(
        "publication_reviews",
        sa.Column(
            "manifest_id", sa.Uuid(), sa.ForeignKey("publication_manifests.id"), primary_key=True
        ),
        sa.Column("review_id", sa.Uuid(), sa.ForeignKey("object_reviews.id"), primary_key=True),
    )
    for table in ("review_evidence", "publication_reviews"):
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} "
                f"ON {table} BEGIN SELECT RAISE(ABORT, 'review links are immutable'); END"
            )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup; research history cannot be discarded.")

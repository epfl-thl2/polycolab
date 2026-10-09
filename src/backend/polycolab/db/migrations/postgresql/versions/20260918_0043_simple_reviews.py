"""Allow review acknowledgement without a correctness assessment."""

from alembic import op

revision = "20260918_simple_reviews"
down_revision = "20260918_object_semantics"
branch_labels = None
depends_on = None

CONSTRAINT = (
    "(withdrawn AND outcome IS NULL) OR (NOT withdrawn AND outcome IS NOT NULL "
    "AND outcome IN ('REVIEWED', 'SUPPORTS', 'ISSUES_FOUND', 'INCONCLUSIVE'))"
)


def upgrade() -> None:
    op.drop_constraint("ck_object_reviews_outcome", "object_reviews", type_="check")
    op.create_check_constraint("ck_object_reviews_outcome", "object_reviews", CONSTRAINT)


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup; review history cannot be discarded.")

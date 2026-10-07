"""Allow review acknowledgement without a correctness assessment."""

from alembic import op

revision = "local_20260918_simple_reviews"
down_revision = "local_20260918_object_semantics"
branch_labels = None
depends_on = None

CONSTRAINT = (
    "(withdrawn AND outcome IS NULL) OR (NOT withdrawn AND outcome IS NOT NULL "
    "AND outcome IN ('REVIEWED', 'SUPPORTS', 'ISSUES_FOUND', 'INCONCLUSIVE'))"
)


def upgrade() -> None:
    with op.batch_alter_table("object_reviews") as batch:
        batch.drop_constraint("ck_object_reviews_outcome", type_="check")
        batch.create_check_constraint("ck_object_reviews_outcome", CONSTRAINT)
    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER object_reviews_no_{operation.lower()} BEFORE {operation} "
            "ON object_reviews BEGIN SELECT RAISE(ABORT, 'reviews are immutable'); END"
        )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup; review history cannot be discarded.")

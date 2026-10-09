"""Permanent system numbers for research submissions."""

import sqlalchemy as sa
from alembic import op

revision = "20260915_submission_numbers"
down_revision = "20260914_unified_deployment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE research_activity_events IN ACCESS EXCLUSIVE MODE")
    op.create_table(
        "research_submission_counter",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_submission_counter_singleton"),
        sa.CheckConstraint("value >= 0", name="ck_submission_counter_nonnegative"),
    )
    op.add_column("research_activity_events", sa.Column("submission_number", sa.BigInteger()))
    op.execute(
        "ALTER TABLE research_activity_events DISABLE TRIGGER research_activity_events_immutable"
    )
    op.execute("""
        WITH numbered AS (
            SELECT id, row_number() OVER (ORDER BY occurred_at, id) AS number
            FROM research_activity_events
        )
        UPDATE research_activity_events AS event SET submission_number = numbered.number
        FROM numbered WHERE event.id = numbered.id
    """)
    op.execute(
        "ALTER TABLE research_activity_events ENABLE TRIGGER research_activity_events_immutable"
    )
    op.alter_column("research_activity_events", "submission_number", nullable=False)
    op.create_unique_constraint(
        "uq_research_activity_events_submission_number",
        "research_activity_events",
        ["submission_number"],
    )
    op.execute(
        "INSERT INTO research_submission_counter (id, value) "
        "SELECT 1, COALESCE(MAX(submission_number), 0) FROM research_activity_events"
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_research_activity_events_submission_number", "research_activity_events", type_="unique"
    )
    op.drop_column("research_activity_events", "submission_number")
    op.drop_table("research_submission_counter")

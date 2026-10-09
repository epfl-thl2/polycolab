"""Add the canonical oldest-outbox-event telemetry index."""

from alembic import op

revision = "20260908_outbox_telemetry_index"
down_revision = "20260908_scheduler_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_outbox_events_created_at",
            "outbox_events",
            ["created_at", "id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_outbox_events_created_at",
            table_name="outbox_events",
            postgresql_concurrently=True,
        )

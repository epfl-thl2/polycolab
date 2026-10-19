"""Add private provider-only chat."""

from polycolab.db.migrations.chat_schema import upgrade as upgrade

revision = "20261014_chat"
down_revision = "20261013_linear"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching database backup.")

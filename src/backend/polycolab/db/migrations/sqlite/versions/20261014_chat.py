"""Add private provider-only chat."""

from polycolab.db.migrations.chat_schema import upgrade as upgrade

revision = "local_20261014_chat"
down_revision = "local_20261013_linear"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching database backup.")

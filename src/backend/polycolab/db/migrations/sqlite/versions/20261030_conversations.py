"""Canonical conversations and semantic transcript items."""

from polycolab.db.migrations.conversations import upgrade as upgrade

revision = "local_20261030_conversations"
down_revision = "local_20261028_chat_latex"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

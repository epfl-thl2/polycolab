"""Use conversation IDs and explicit conversation sharing names."""

from polycolab.db.migrations.conversation_names import upgrade as upgrade

revision = "local_20261115_conversation_names"
down_revision = "local_20261115_roles"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

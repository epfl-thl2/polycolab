"""Use Basic and Collaborative file modes and agent change sets."""

from polycolab.db.migrations.file_mode_names import upgrade as upgrade

revision = "local_20261115_file_modes"
down_revision = "local_20261115_conversation_names"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

"""Name reusable content library items."""

from polycolab.db.migrations.library_names import upgrade as upgrade

revision = "20261115_library_names"
down_revision = "20261115_file_modes"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

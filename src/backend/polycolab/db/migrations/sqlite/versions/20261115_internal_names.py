"""Name execution jobs, scheduling scopes, idempotency records and reconciliation."""

from polycolab.db.migrations.internal_names import upgrade as upgrade

revision = "local_20261115_internal_names"
down_revision = "local_20261115_library_names"
branch_labels = None
depends_on = None


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

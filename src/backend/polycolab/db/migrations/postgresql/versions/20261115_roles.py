"""Rename project roles without changing their permissions."""

from alembic import op

revision = "20261115_roles"
down_revision = "20261115_provider_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("memberships", "invitations"):
        op.execute(f"UPDATE {table} SET role = 'EDITOR' WHERE role = 'CONTRIBUTOR'")
        op.execute(f"UPDATE {table} SET role = 'VIEWER' WHERE role = 'READ_ONLY'")


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

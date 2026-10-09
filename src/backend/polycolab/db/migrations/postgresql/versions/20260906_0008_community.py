"""Independent unique human follows and interest votes."""

from alembic import op

revision = "20260906_community"
down_revision = "20260906_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("catalogue_follows", "catalogue_interest"):
        op.execute(f"""
CREATE TABLE {table} (
 user_id UUID NOT NULL REFERENCES users(id),
 entry_id UUID NOT NULL REFERENCES catalogue_entries(id),
 active BOOLEAN NOT NULL,
 PRIMARY KEY (user_id, entry_id)
)
""")
        op.execute(f"CREATE INDEX ix_{table}_entry_id ON {table}(entry_id)")


def downgrade() -> None:
    raise RuntimeError("Retain community state; disable new participation instead.")

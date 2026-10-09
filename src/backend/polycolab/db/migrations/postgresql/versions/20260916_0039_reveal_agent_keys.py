"""Store encrypted agent key secrets for owner-only reveal."""

import sqlalchemy as sa
from alembic import op

revision = "20260916_reveal_agent_keys"
down_revision = "20260916_merge_hosted_main"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "external_agent_credentials", sa.Column("encrypted_secret", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "external_agent_credentials", sa.Column("wrapped_data_key", sa.LargeBinary(), nullable=True)
    )
    op.add_column(
        "external_agent_credentials",
        sa.Column("encryption_key_version", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("Restore the pre-upgrade backup to preserve recoverable credentials.")

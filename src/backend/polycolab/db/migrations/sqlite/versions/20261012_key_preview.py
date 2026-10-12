"""Store a masked recognition preview for provider credentials."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261012_key_preview"
down_revision = "local_20261011_native_worktrees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("gateway_profiles", sa.Column("api_key_preview", sa.String(11), nullable=True))


def downgrade() -> None:
    op.drop_column("gateway_profiles", "api_key_preview")

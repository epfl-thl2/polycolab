"""Merge workspace-only and canonical session histories without rewriting either."""

revision = "20261103_session_workspace"
down_revision = ("20261029_workspace_only", "20261030_conversations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

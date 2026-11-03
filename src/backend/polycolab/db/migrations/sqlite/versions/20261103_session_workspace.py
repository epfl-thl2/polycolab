"""Merge workspace-only and canonical session histories without rewriting either."""

revision = "local_20261103_session_workspace"
down_revision = ("local_20261029_workspace_only", "local_20261030_conversations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

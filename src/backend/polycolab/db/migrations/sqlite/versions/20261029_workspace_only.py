"""Remove the research database and keep project-owned workspace execution."""

from polycolab.db.migrations.workspace_only import downgrade as downgrade
from polycolab.db.migrations.workspace_only import upgrade as upgrade

revision = "local_20261029_workspace_only"
down_revision = "local_20261028_chat_latex"
branch_labels = None
depends_on = None

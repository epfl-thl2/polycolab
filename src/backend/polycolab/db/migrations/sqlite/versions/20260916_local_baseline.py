"""Frozen local schema corresponding to the PostgreSQL schema on 2026-09-16."""

import json
from pathlib import Path

from alembic import op

revision = "local_20260916"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = json.loads(Path(__file__).with_name("20260916_schema.json").read_text())
    for statement in statements:
        op.execute(statement)
    op.execute("INSERT INTO research_submission_counter (id, value) VALUES (1, 0)")
    op.execute(
        "INSERT INTO research_scopes (id, scope_kind, project_id, created_at) "
        "VALUES ('00000000000040008000000000000001', 'COMMONS', NULL, CURRENT_TIMESTAMP)"
    )


def downgrade() -> None:
    raise RuntimeError("Local downgrades are unsupported; restore the pre-upgrade backup.")

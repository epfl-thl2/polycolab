"""Rename provider profiles while preserving credential envelopes and references."""

from alembic import op

revision = "local_20261104_provider_profiles"
down_revision = "local_20261104_worktrees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("gateway_profiles", "provider_profiles")
    op.alter_column("agent_runs", "gateway_profile_id", new_column_name="provider_profile_id")
    op.drop_index("ix_gateway_profiles_user_id", table_name="provider_profiles")
    op.create_index("ix_provider_profiles_user_id", "provider_profiles", ["user_id"])
    op.drop_index("ix_agent_runs_gateway_profile_id", table_name="agent_runs")
    op.create_index("ix_agent_runs_provider_profile_id", "agent_runs", ["provider_profile_id"])
    # Native renames preserve inbound foreign keys and all credential bytes.


def downgrade() -> None:
    raise RuntimeError("Restore the matching database and application backups.")

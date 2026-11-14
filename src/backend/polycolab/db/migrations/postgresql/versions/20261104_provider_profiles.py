"""Rename provider profiles while preserving credential envelopes and references."""

from alembic import op

revision = "20261104_provider_profiles"
down_revision = "20261104_worktrees"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("gateway_profiles", "provider_profiles")
    op.alter_column("agent_runs", "gateway_profile_id", new_column_name="provider_profile_id")
    op.execute("ALTER INDEX ix_gateway_profiles_user_id RENAME TO ix_provider_profiles_user_id")
    op.execute(
        "ALTER INDEX ix_agent_runs_gateway_profile_id RENAME TO ix_agent_runs_provider_profile_id"
    )
    op.execute("""
DO $profiles$
DECLARE item RECORD;
BEGIN
 FOR item IN
   SELECT conrelid::regclass::text AS tbl, conname AS name FROM pg_constraint
   WHERE connamespace=current_schema()::regnamespace
     AND (conname LIKE 'gateway_profiles_%' OR conname LIKE '%gateway_profile_id%')
 LOOP
   EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', item.tbl, item.name,
                  replace(item.name, 'gateway_profile', 'provider_profile'));
 END LOOP;
END $profiles$;
""")
    # Ciphertexts and their authenticated encryption contexts are intentionally unchanged.


def downgrade() -> None:
    raise RuntimeError("Restore the matching database and application backups.")

"""Record global protected-access invalidation after a beta restore."""

from alembic import op

revision = "20260909_restore_invalidation"
down_revision = "20260909_external_agents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE operator_restore_invalidations (
 id UUID PRIMARY KEY,
 recovery_reference_digest VARCHAR(64) NOT NULL,
 revoked_session_count INTEGER NOT NULL,
 revoked_credential_count INTEGER NOT NULL,
 revoked_run_count INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_operator_restore_invalidation_reference
  CHECK (length(recovery_reference_digest) = 64),
 CONSTRAINT ck_operator_restore_invalidation_counts
  CHECK (revoked_session_count >= 0 AND revoked_credential_count >= 0
   AND revoked_run_count >= 0)
);
"""
    )


def downgrade() -> None:
    op.drop_table("operator_restore_invalidations")

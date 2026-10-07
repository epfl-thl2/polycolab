"""Add built-in self-registration invitations and durable admission scope."""

from alembic import op

revision = "20260908_registration_foundation"
down_revision = "20260908_social_auth_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE registration_invitations (
 id UUID PRIMARY KEY,
 code_digest VARCHAR(64) NOT NULL,
 created_by_account_id UUID NOT NULL REFERENCES local_accounts(id),
 expires_at TIMESTAMPTZ NOT NULL,
 status VARCHAR(16) NOT NULL,
 accepted_by_account_id UUID REFERENCES local_accounts(id),
 accepted_at TIMESTAMPTZ,
 revoked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_registration_invitation_digest CHECK (length(code_digest) = 64),
 CONSTRAINT ck_registration_invitation_expiry CHECK (expires_at > created_at),
 CONSTRAINT ck_registration_invitation_status CHECK
   (status IN ('PENDING', 'ACCEPTED', 'REVOKED')),
 CONSTRAINT ck_registration_invitation_state CHECK
   ((status = 'PENDING' AND accepted_by_account_id IS NULL AND
     accepted_at IS NULL AND revoked_at IS NULL) OR
    (status = 'ACCEPTED' AND accepted_by_account_id IS NOT NULL AND
     accepted_at IS NOT NULL AND revoked_at IS NULL) OR
    (status = 'REVOKED' AND accepted_by_account_id IS NULL AND
     accepted_at IS NULL AND revoked_at IS NOT NULL))
)
""")
    op.execute(
        "CREATE UNIQUE INDEX ix_registration_invitations_code_digest "
        "ON registration_invitations(code_digest)"
    )
    op.execute(
        "CREATE INDEX ix_registration_invitations_created_by_account_id "
        "ON registration_invitations(created_by_account_id)"
    )
    op.execute(
        "CREATE INDEX ix_registration_invitations_expires_at "
        "ON registration_invitations(expires_at)"
    )
    op.execute("ALTER TABLE execution_rate_windows DROP CONSTRAINT ck_execution_rate_window_scope")
    op.execute("""
ALTER TABLE execution_rate_windows ADD CONSTRAINT ck_execution_rate_window_scope
CHECK (scope IN ('user', 'project', 'public_ip', 'sse_user', 'registration_ip'))
""")


def downgrade() -> None:
    op.execute("DELETE FROM execution_rate_windows WHERE scope = 'registration_ip'")
    op.execute("ALTER TABLE execution_rate_windows DROP CONSTRAINT ck_execution_rate_window_scope")
    op.execute("""
ALTER TABLE execution_rate_windows ADD CONSTRAINT ck_execution_rate_window_scope
CHECK (scope IN ('user', 'project', 'public_ip', 'sse_user'))
""")
    op.execute("DROP TABLE registration_invitations")

"""Add optional verified email, recovery tokens and encrypted mail outbox."""

from alembic import op

revision = "20260909_beta_recovery"
down_revision = "20260909_beta_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE auth_sessions ADD COLUMN password_reauthenticated_at TIMESTAMPTZ NULL")
    op.execute(
        """
CREATE TABLE account_emails (
 account_id UUID PRIMARY KEY REFERENCES local_accounts(id),
 verified_email VARCHAR(320) NULL UNIQUE,
 verified_at TIMESTAMPTZ NULL,
 pending_email VARCHAR(320) NULL,
 pending_requested_at TIMESTAMPTZ NULL,
 created_at TIMESTAMPTZ NOT NULL,
 updated_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_account_email_verified_state CHECK
  ((verified_email IS NULL) = (verified_at IS NULL)),
 CONSTRAINT ck_account_email_pending_state CHECK
  ((pending_email IS NULL) = (pending_requested_at IS NULL))
)
"""
    )
    op.execute(
        """
CREATE TABLE account_recovery_tokens (
 id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES local_accounts(id),
 purpose VARCHAR(32) NOT NULL,
 email VARCHAR(320) NOT NULL,
 token_digest VARCHAR(64) NOT NULL UNIQUE,
 expires_at TIMESTAMPTZ NOT NULL,
 consumed_at TIMESTAMPTZ NULL,
 invalidated_at TIMESTAMPTZ NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_account_recovery_token_purpose CHECK
  (purpose IN ('EMAIL_VERIFICATION','PASSWORD_RESET')),
 CONSTRAINT ck_account_recovery_token_digest CHECK (length(token_digest) = 64),
 CONSTRAINT ck_account_recovery_token_expiry CHECK (expires_at > created_at),
 CONSTRAINT ck_account_recovery_token_terminal CHECK
  (consumed_at IS NULL OR invalidated_at IS NULL)
)
"""
    )
    op.execute(
        "CREATE INDEX ix_account_recovery_tokens_account_id ON account_recovery_tokens(account_id)"
    )
    op.execute(
        "CREATE INDEX ix_account_recovery_tokens_expires_at ON account_recovery_tokens(expires_at)"
    )
    op.execute(
        "CREATE INDEX ix_account_recovery_tokens_active "
        "ON account_recovery_tokens(account_id, purpose, expires_at)"
    )
    op.execute(
        """
CREATE TABLE mail_outbox (
 id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES local_accounts(id),
 token_id UUID NOT NULL UNIQUE REFERENCES account_recovery_tokens(id),
 purpose VARCHAR(32) NOT NULL,
 encrypted_payload BYTEA NULL,
 wrapped_data_key BYTEA NULL,
 encryption_key_version VARCHAR(200) NULL,
 payload_digest VARCHAR(64) NULL,
 status VARCHAR(16) NOT NULL,
 attempts INTEGER NOT NULL,
 claim_generation INTEGER NOT NULL,
 available_at TIMESTAMPTZ NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 claimed_by VARCHAR(100) NULL,
 claimed_at TIMESTAMPTZ NULL,
 terminal_at TIMESTAMPTZ NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_mail_outbox_purpose CHECK
  (purpose IN ('EMAIL_VERIFICATION','PASSWORD_RESET')),
 CONSTRAINT ck_mail_outbox_status CHECK
  (status IN ('PENDING','CLAIMED','DELIVERED','CANCELLED','EXPIRED','DISCARDED')),
 CONSTRAINT ck_mail_outbox_attempts CHECK (attempts >= 0),
 CONSTRAINT ck_mail_outbox_claim_generation CHECK (claim_generation >= 0),
 CONSTRAINT ck_mail_outbox_expiry CHECK (expires_at > created_at),
 CONSTRAINT ck_mail_outbox_payload_lifecycle CHECK (
  (status IN ('PENDING','CLAIMED') AND encrypted_payload IS NOT NULL
   AND wrapped_data_key IS NOT NULL AND encryption_key_version IS NOT NULL
   AND payload_digest IS NOT NULL)
  OR
  (status IN ('DELIVERED','CANCELLED','EXPIRED','DISCARDED')
   AND encrypted_payload IS NULL AND wrapped_data_key IS NULL
   AND encryption_key_version IS NULL)
 )
)
"""
    )
    op.execute("CREATE INDEX ix_mail_outbox_account_id ON mail_outbox(account_id)")
    op.execute("CREATE INDEX ix_mail_outbox_expires_at ON mail_outbox(expires_at)")
    op.execute(
        "CREATE INDEX ix_mail_outbox_claim ON mail_outbox(status, available_at, created_at, id)"
    )
    op.execute(
        """
CREATE TABLE account_recovery_rate_windows (
 id UUID PRIMARY KEY,
 action VARCHAR(32) NOT NULL,
 scope_digest VARCHAR(64) NOT NULL,
 window_started_at TIMESTAMPTZ NOT NULL,
 count INTEGER NOT NULL,
 CONSTRAINT uq_account_recovery_rate_window UNIQUE
  (action, scope_digest, window_started_at),
 CONSTRAINT ck_account_recovery_rate_action CHECK
  (action IN ('EMAIL_CHANGE','EMAIL_RESEND','PASSWORD_RESET')),
 CONSTRAINT ck_account_recovery_rate_digest CHECK (length(scope_digest) = 64),
 CONSTRAINT ck_account_recovery_rate_count CHECK (count >= 0)
)
"""
    )
    op.execute(
        "CREATE INDEX ix_account_recovery_rate_windows_scope_digest "
        "ON account_recovery_rate_windows(scope_digest)"
    )
    op.execute(
        "CREATE INDEX ix_account_recovery_rate_windows_window_started_at "
        "ON account_recovery_rate_windows(window_started_at)"
    )


def downgrade() -> None:
    op.drop_table("account_recovery_rate_windows")
    op.drop_table("mail_outbox")
    op.drop_table("account_recovery_tokens")
    op.drop_table("account_emails")
    op.drop_column("auth_sessions", "password_reauthenticated_at")

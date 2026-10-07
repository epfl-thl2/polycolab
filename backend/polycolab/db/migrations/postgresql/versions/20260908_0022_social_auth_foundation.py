"""Add durable direct social-auth identities and single-use flow state."""

from alembic import op

revision = "20260908_social_auth_foundation"
down_revision = "20260908_outbox_telemetry_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE local_accounts ALTER COLUMN password_digest DROP NOT NULL")
    op.execute("ALTER TABLE auth_sessions ADD COLUMN reauthenticated_at TIMESTAMPTZ")
    op.execute("UPDATE auth_sessions SET reauthenticated_at = created_at")
    op.execute("ALTER TABLE auth_sessions ALTER COLUMN reauthenticated_at SET NOT NULL")
    op.execute("""
CREATE TABLE social_account_identities (
 id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES local_accounts(id),
 provider VARCHAR(16) NOT NULL,
 subject VARCHAR(255) NOT NULL,
 unlinked_at TIMESTAMPTZ,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_social_identity_provider_subject UNIQUE (provider, subject),
 CONSTRAINT uq_social_identity_account_provider UNIQUE (account_id, provider),
 CONSTRAINT ck_social_identity_provider CHECK (provider IN ('google', 'github')),
 CONSTRAINT ck_social_identity_subject_length CHECK (length(subject) BETWEEN 1 AND 255)
)
""")
    op.execute(
        "CREATE INDEX ix_social_account_identities_account_id "
        "ON social_account_identities(account_id)"
    )
    op.execute("""
CREATE TABLE social_auth_transactions (
 id UUID PRIMARY KEY,
 state_digest VARCHAR(64) NOT NULL,
 browser_binding_digest VARCHAR(64) NOT NULL,
 provider VARCHAR(16) NOT NULL,
 purpose VARCHAR(16) NOT NULL,
 pkce_verifier VARCHAR(128) NOT NULL,
 nonce VARCHAR(128) NOT NULL,
 return_path VARCHAR(500) NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 consumed_at TIMESTAMPTZ,
 linked_account_id UUID REFERENCES local_accounts(id),
 linked_session_id UUID REFERENCES auth_sessions(id),
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_social_auth_transaction_provider CHECK (provider IN ('google', 'github')),
 CONSTRAINT ck_social_auth_transaction_purpose CHECK (purpose IN ('SIGN_IN', 'LINK')),
 CONSTRAINT ck_social_auth_transaction_digest_length CHECK
   (length(state_digest) = 64 AND length(browser_binding_digest) = 64),
 CONSTRAINT ck_social_auth_transaction_secret_length CHECK
   (length(pkce_verifier) BETWEEN 43 AND 128 AND length(nonce) BETWEEN 32 AND 128),
 CONSTRAINT ck_social_auth_transaction_return_path_length CHECK
   (length(return_path) BETWEEN 1 AND 500),
 CONSTRAINT ck_social_auth_transaction_expiry CHECK (expires_at > created_at),
 CONSTRAINT ck_social_auth_transaction_link_binding CHECK
   ((purpose = 'SIGN_IN' AND linked_account_id IS NULL AND linked_session_id IS NULL) OR
    (purpose = 'LINK' AND linked_account_id IS NOT NULL AND linked_session_id IS NOT NULL))
)
""")
    op.execute(
        "CREATE UNIQUE INDEX ix_social_auth_transactions_state_digest "
        "ON social_auth_transactions(state_digest)"
    )
    op.execute(
        "CREATE INDEX ix_social_auth_transactions_expires_at "
        "ON social_auth_transactions(expires_at)"
    )
    op.execute("""
CREATE TABLE social_identity_audits (
 id UUID PRIMARY KEY,
 identity_id UUID NOT NULL REFERENCES social_account_identities(id),
 account_id UUID NOT NULL REFERENCES local_accounts(id),
 actor_account_id UUID REFERENCES local_accounts(id),
 action VARCHAR(16) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_social_identity_audit_action CHECK
   (action IN ('CREATED', 'LINKED', 'UNLINKED', 'RELINKED')),
 CONSTRAINT ck_social_identity_audit_actor CHECK
   ((action = 'CREATED' AND actor_account_id IS NULL) OR
    (action <> 'CREATED' AND actor_account_id IS NOT NULL))
)
""")
    op.execute(
        "CREATE INDEX ix_social_identity_audits_identity_id ON social_identity_audits(identity_id)"
    )
    op.execute(
        "CREATE INDEX ix_social_identity_audits_account_id ON social_identity_audits(account_id)"
    )
    op.execute("""
CREATE FUNCTION protect_social_identity_binding() RETURNS trigger AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'social identity bindings cannot be deleted';
 END IF;
 IF NEW.id <> OLD.id OR NEW.account_id <> OLD.account_id OR
    NEW.provider <> OLD.provider OR NEW.subject <> OLD.subject OR
    NEW.created_at <> OLD.created_at THEN
   RAISE EXCEPTION 'social identity binding is immutable';
 END IF;
 RETURN NEW;
END;
$$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER trg_social_identity_binding
BEFORE UPDATE OR DELETE ON social_account_identities
FOR EACH ROW EXECUTE FUNCTION protect_social_identity_binding()
""")
    op.execute("""
CREATE FUNCTION protect_social_identity_audit() RETURNS trigger AS $$
BEGIN
 RAISE EXCEPTION 'social identity audit is immutable';
END;
$$ LANGUAGE plpgsql
""")
    op.execute("""
CREATE TRIGGER trg_social_identity_audit
BEFORE UPDATE OR DELETE ON social_identity_audits
FOR EACH ROW EXECUTE FUNCTION protect_social_identity_audit()
""")


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_social_identity_audit ON social_identity_audits")
    op.execute("DROP FUNCTION protect_social_identity_audit()")
    op.execute("DROP TRIGGER trg_social_identity_binding ON social_account_identities")
    op.execute("DROP FUNCTION protect_social_identity_binding()")
    op.execute("DROP TABLE social_identity_audits")
    op.execute("DROP TABLE social_auth_transactions")
    op.execute("DROP TABLE social_account_identities")
    op.execute("ALTER TABLE auth_sessions DROP COLUMN reauthenticated_at")
    op.execute("ALTER TABLE local_accounts ALTER COLUMN password_digest SET NOT NULL")

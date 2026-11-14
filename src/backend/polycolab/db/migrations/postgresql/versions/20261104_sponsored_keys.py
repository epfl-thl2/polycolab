"""Detach external credentials from retired agent identities, preserving key bytes."""

from alembic import op

revision = "20261104_sponsored_keys"
down_revision = "20261103_session_workspace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the grant immutable after removing its obsolete identity reference.
    # Ciphertext, encryption contexts, budgets and immutable receipt payloads are
    # unchanged. PostgreSQL drops this column's local constraints and indexes.
    op.execute("""
CREATE OR REPLACE FUNCTION external_agent_credential_grant_immutable() RETURNS trigger AS $$
BEGIN
 IF NEW.project_id IS DISTINCT FROM OLD.project_id
 OR NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
 OR NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id
 OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
 OR NEW.fixed_rights::jsonb IS DISTINCT FROM OLD.fixed_rights::jsonb
 OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
 OR NEW.max_requests IS DISTINCT FROM OLD.max_requests
 OR NEW.max_mutations IS DISTINCT FROM OLD.max_mutations
 THEN RAISE EXCEPTION 'external agent credential grant is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
""")
    op.drop_column("external_agent_credentials", "agent_id")
    op.drop_table("external_agent_identities")
    op.execute("DROP FUNCTION protect_external_agent_identity()")


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

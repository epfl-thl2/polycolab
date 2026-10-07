"""Account-wide agent grants; retire workspace secrets without deleting history."""

import sqlalchemy as sa
from alembic import op

revision = "20260910_account_agent_keys"
down_revision = "20260910_credential_rights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "DROP TRIGGER external_agent_credential_grant_immutable ON external_agent_credentials"
    )
    op.execute(
        "UPDATE external_agent_credentials SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP)"
    )
    op.execute(
        "UPDATE external_research_runs SET status = 'REVOKED', closed_at = CURRENT_TIMESTAMP "
        "WHERE status = 'OPEN'"
    )
    op.add_column(
        "external_agent_credentials",
        sa.Column("scope_kind", sa.String(16), nullable=False, server_default="WORKSPACE"),
    )
    op.alter_column("external_agent_credentials", "scope_kind", server_default=None)
    op.alter_column("external_agent_credentials", "project_id", nullable=True)
    op.create_unique_constraint(
        "uq_external_credential_sponsor", "external_agent_credentials", ["id", "sponsor_user_id"]
    )
    op.create_check_constraint(
        "ck_external_credential_scope",
        "external_agent_credentials",
        "(scope_kind = 'ACCOUNT' AND project_id IS NULL) OR "
        "(scope_kind = 'WORKSPACE' AND project_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_external_run_credential_binding", "external_research_runs", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_external_run_credential_binding",
        "external_research_runs",
        "external_agent_credentials",
        ["credential_id", "sponsor_user_id"],
        ["id", "sponsor_user_id"],
    )
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
CREATE TRIGGER external_agent_credential_grant_immutable BEFORE UPDATE ON external_agent_credentials
FOR EACH ROW EXECUTE FUNCTION external_agent_credential_grant_immutable();
""")


def downgrade() -> None:
    raise RuntimeError(
        "Account-wide credentials require a forward repair; "
        "do not restore old application code against this schema"
    )

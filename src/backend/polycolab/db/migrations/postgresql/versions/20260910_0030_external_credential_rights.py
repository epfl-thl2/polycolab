"""Persist immutable fixed rights for external-agent credentials."""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260910_credential_rights"
down_revision = "20260909_restore_invalidation"
branch_labels = None
depends_on = None

FIXED_RIGHTS = [
    "CONTRIBUTION_CREATE",
    "CONTRIBUTION_EDIT",
    "PUBLIC_PARTICIPATION",
    "WORKSPACE_WRITE",
]


def upgrade() -> None:
    op.add_column(
        "external_agent_credentials",
        sa.Column("fixed_rights", sa.JSON(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE external_agent_credentials SET fixed_rights = CAST(:fixed_rights AS JSON)"
        ).bindparams(fixed_rights=json.dumps(FIXED_RIGHTS))
    )
    op.alter_column("external_agent_credentials", "fixed_rights", nullable=False)
    op.execute(
        """
CREATE FUNCTION external_agent_credential_grant_immutable() RETURNS trigger AS $$
BEGIN
 IF NEW.project_id IS DISTINCT FROM OLD.project_id
    OR NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id
    OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
    OR NEW.fixed_rights::jsonb IS DISTINCT FROM OLD.fixed_rights::jsonb
    OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
    OR NEW.max_requests IS DISTINCT FROM OLD.max_requests
    OR NEW.max_mutations IS DISTINCT FROM OLD.max_mutations
 THEN RAISE EXCEPTION 'external agent credential grant is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER external_agent_credential_grant_immutable
BEFORE UPDATE ON external_agent_credentials FOR EACH ROW
EXECUTE FUNCTION external_agent_credential_grant_immutable();
"""
    )


def downgrade() -> None:
    op.execute(
        """
DROP TRIGGER external_agent_credential_grant_immutable ON external_agent_credentials;
DROP FUNCTION external_agent_credential_grant_immutable();
"""
    )
    op.drop_column("external_agent_credentials", "fixed_rights")

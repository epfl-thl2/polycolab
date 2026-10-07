"""Add single-workspace external credentials, runs and direct provenance."""

import sqlalchemy as sa
from alembic import op

revision = "20260909_external_agents"
down_revision = "20260909_beta_public_workspaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE external_agent_credentials (
 id UUID PRIMARY KEY,
 project_id UUID NOT NULL REFERENCES projects(id),
 sponsor_user_id UUID NOT NULL REFERENCES users(id),
 name VARCHAR(200) NOT NULL,
 token_digest VARCHAR(64) NOT NULL,
 expires_at TIMESTAMPTZ NOT NULL,
 revoked_at TIMESTAMPTZ,
 request_count INTEGER NOT NULL DEFAULT 0,
 mutation_count INTEGER NOT NULL DEFAULT 0,
 max_requests INTEGER NOT NULL,
 max_mutations INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_external_agent_credential_identity UNIQUE (id, project_id, sponsor_user_id),
 CONSTRAINT ck_external_agent_token_digest CHECK (length(token_digest) = 64),
 CONSTRAINT ck_external_agent_request_count CHECK (request_count >= 0),
 CONSTRAINT ck_external_agent_mutation_count CHECK (mutation_count >= 0),
 CONSTRAINT ck_external_agent_max_requests CHECK (max_requests > 0),
 CONSTRAINT ck_external_agent_max_mutations CHECK (max_mutations > 0)
);
CREATE INDEX ix_external_agent_credentials_project_id ON external_agent_credentials(project_id);
CREATE INDEX ix_external_agent_credentials_sponsor_user_id
 ON external_agent_credentials(sponsor_user_id);
CREATE UNIQUE INDEX ix_external_agent_credentials_token_digest
 ON external_agent_credentials(token_digest);
CREATE INDEX ix_external_agent_credentials_expires_at ON external_agent_credentials(expires_at);

CREATE TABLE external_research_runs (
 id UUID PRIMARY KEY,
 credential_id UUID NOT NULL REFERENCES external_agent_credentials(id),
 project_id UUID NOT NULL REFERENCES projects(id),
 sponsor_user_id UUID NOT NULL REFERENCES users(id),
 client_request_id UUID NOT NULL,
 title VARCHAR(300),
 input_revision_ids JSON NOT NULL,
 status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
 failure_code VARCHAR(64),
 created_at TIMESTAMPTZ NOT NULL,
 closed_at TIMESTAMPTZ,
 CONSTRAINT fk_external_run_credential_binding
  FOREIGN KEY (credential_id, project_id, sponsor_user_id)
  REFERENCES external_agent_credentials(id, project_id, sponsor_user_id),
 CONSTRAINT uq_external_research_run_identity
  UNIQUE (id, credential_id, project_id, sponsor_user_id),
 CONSTRAINT uq_external_run_client_request UNIQUE (credential_id, client_request_id),
 CONSTRAINT ck_external_research_run_status
  CHECK (status IN ('OPEN','COMPLETED','FAILED','REVOKED'))
);
CREATE INDEX ix_external_research_runs_credential_id ON external_research_runs(credential_id);
CREATE INDEX ix_external_research_runs_project_id ON external_research_runs(project_id);
CREATE INDEX ix_external_research_runs_sponsor_user_id ON external_research_runs(sponsor_user_id);

CREATE TABLE external_run_invocations (
 id UUID PRIMARY KEY,
 run_id UUID NOT NULL REFERENCES external_research_runs(id),
 operation VARCHAR(64) NOT NULL,
 idempotency_digest VARCHAR(64) NOT NULL,
 request_digest VARCHAR(64) NOT NULL,
 output_type VARCHAR(64) NOT NULL,
 output_id UUID NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_external_invocation_key UNIQUE (run_id, idempotency_digest),
 CONSTRAINT ck_external_invocation_key CHECK (length(idempotency_digest) = 64),
 CONSTRAINT ck_external_invocation_request CHECK (length(request_digest) = 64)
);
CREATE INDEX ix_external_run_invocations_run_id ON external_run_invocations(run_id);

CREATE TABLE operator_account_recoveries (
 id UUID PRIMARY KEY,
 account_id UUID NOT NULL REFERENCES local_accounts(id),
 user_id UUID NOT NULL REFERENCES users(id),
 verification_reference_digest VARCHAR(64) NOT NULL,
 revoked_session_count INTEGER NOT NULL,
 revoked_credential_count INTEGER NOT NULL,
 revoked_run_count INTEGER NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT ck_operator_account_recovery_reference
  CHECK (length(verification_reference_digest) = 64),
 CONSTRAINT ck_operator_account_recovery_counts
  CHECK (revoked_session_count >= 0 AND revoked_credential_count >= 0 AND revoked_run_count >= 0)
);
CREATE INDEX ix_operator_account_recoveries_account_id ON operator_account_recoveries(account_id);
CREATE INDEX ix_operator_account_recoveries_user_id ON operator_account_recoveries(user_id);
"""
    )
    op.add_column("contribution_envelopes", sa.Column("external_credential_id", sa.UUID()))
    op.add_column("contribution_envelopes", sa.Column("external_run_id", sa.UUID()))
    op.create_foreign_key(
        "fk_contribution_external_credential",
        "contribution_envelopes",
        "external_agent_credentials",
        ["external_credential_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_contribution_external_run_binding",
        "contribution_envelopes",
        "external_research_runs",
        ["external_run_id", "external_credential_id", "project_id", "sponsor_user_id"],
        ["id", "credential_id", "project_id", "sponsor_user_id"],
    )
    op.create_foreign_key(
        "fk_contribution_external_run",
        "contribution_envelopes",
        "external_research_runs",
        ["external_run_id"],
        ["id"],
    )
    op.drop_constraint(
        "ck_contribution_envelopes_actor_scope", "contribution_envelopes", type_="check"
    )
    op.create_check_constraint(
        "ck_contribution_envelopes_actor_scope",
        "contribution_envelopes",
        "((actor_kind = 'HUMAN' AND human_user_id IS NOT NULL AND sponsor_user_id IS NULL "
        "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
        "AND context_manifest_id IS NULL AND external_credential_id IS NULL "
        "AND external_run_id IS NULL) OR "
        "(actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL "
        "AND agent_version_id IS NOT NULL AND run_id IS NOT NULL AND session_id IS NOT NULL "
        "AND context_manifest_id IS NOT NULL AND project_id IS NOT NULL "
        "AND external_credential_id IS NULL AND external_run_id IS NULL) OR "
        "(actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL "
        "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
        "AND context_manifest_id IS NULL AND project_id IS NOT NULL "
        "AND external_credential_id IS NOT NULL AND external_run_id IS NOT NULL))",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contribution_external_run_binding", "contribution_envelopes", type_="foreignkey"
    )
    op.drop_constraint(
        "ck_contribution_envelopes_actor_scope", "contribution_envelopes", type_="check"
    )
    op.create_check_constraint(
        "ck_contribution_envelopes_actor_scope",
        "contribution_envelopes",
        "((actor_kind = 'HUMAN' AND human_user_id IS NOT NULL AND sponsor_user_id IS NULL "
        "AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL "
        "AND context_manifest_id IS NULL) OR (actor_kind = 'AGENT' AND human_user_id IS NULL "
        "AND sponsor_user_id IS NOT NULL AND agent_version_id IS NOT NULL AND run_id IS NOT NULL "
        "AND session_id IS NOT NULL AND context_manifest_id IS NOT NULL "
        "AND project_id IS NOT NULL))",
    )
    op.drop_column("contribution_envelopes", "external_run_id")
    op.drop_column("contribution_envelopes", "external_credential_id")
    op.drop_table("operator_account_recoveries")
    op.drop_table("external_run_invocations")
    op.drop_table("external_research_runs")
    op.drop_table("external_agent_credentials")

"""Stable external identities and durable research activity."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_contribution_history"
down_revision = "20260911_library_agent_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_agent_identities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sponsor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "sponsor_user_id", name="uq_external_identity_sponsor"),
    )
    op.create_index(
        "ix_external_agent_identities_sponsor_user_id",
        "external_agent_identities",
        ["sponsor_user_id"],
    )
    op.execute(
        "DROP TRIGGER external_agent_credential_grant_immutable ON external_agent_credentials"
    )
    op.add_column(
        "external_agent_credentials",
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("external_agent_identities.id")),
    )
    op.add_column(
        "external_agent_credentials",
        sa.Column(
            "allow_library_contributions", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column(
        "external_agent_credentials", "allow_library_contributions", server_default=None
    )
    op.create_index(
        "ix_external_agent_credentials_agent_id", "external_agent_credentials", ["agent_id"]
    )
    # Preserve one identity per historical key. Equal display names do not imply identity.
    op.execute(
        "INSERT INTO external_agent_identities (id, sponsor_user_id, name, created_at) "
        "SELECT id, sponsor_user_id, name, created_at FROM external_agent_credentials"
    )
    op.execute("UPDATE external_agent_credentials SET agent_id = id")
    op.create_unique_constraint(
        "uq_external_credential_agent",
        "external_agent_credentials",
        ["id", "agent_id", "sponsor_user_id"],
    )
    op.create_foreign_key(
        "fk_credential_agent_sponsor",
        "external_agent_credentials",
        "external_agent_identities",
        ["agent_id", "sponsor_user_id"],
        ["id", "sponsor_user_id"],
    )
    op.execute("""
CREATE FUNCTION protect_external_agent_identity() RETURNS trigger AS $$
BEGIN
 IF NEW.id IS DISTINCT FROM OLD.id OR NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id
 OR NEW.created_at IS DISTINCT FROM OLD.created_at
 THEN RAISE EXCEPTION 'agent ownership is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER external_agent_identity_owner BEFORE UPDATE ON external_agent_identities
FOR EACH ROW EXECUTE FUNCTION protect_external_agent_identity();
""")
    op.execute("""
CREATE OR REPLACE FUNCTION external_agent_credential_grant_immutable() RETURNS trigger AS $$
BEGIN
 IF NEW.project_id IS DISTINCT FROM OLD.project_id
 OR NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
 OR NEW.sponsor_user_id IS DISTINCT FROM OLD.sponsor_user_id
 OR NEW.agent_id IS DISTINCT FROM OLD.agent_id
 OR NEW.allow_library_contributions IS DISTINCT FROM OLD.allow_library_contributions
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
    op.add_column(
        "contribution_envelopes",
        sa.Column("external_agent_id", sa.Uuid(), sa.ForeignKey("external_agent_identities.id")),
    )
    op.create_index(
        "ix_contribution_envelopes_external_agent_id",
        "contribution_envelopes",
        ["external_agent_id"],
    )
    op.create_foreign_key(
        "fk_contribution_stable_actor",
        "contribution_envelopes",
        "external_agent_credentials",
        ["external_credential_id", "external_agent_id", "sponsor_user_id"],
        ["id", "agent_id", "sponsor_user_id"],
    )
    # Historical envelopes retain their original immutable run binding. Readers can
    # resolve their stable identity through the migrated credential.
    op.drop_constraint(
        "ck_contribution_envelopes_actor_scope", "contribution_envelopes", type_="check"
    )
    op.create_check_constraint(
        "ck_contribution_envelopes_actor_scope",
        "contribution_envelopes",
        """
 ((actor_kind = 'HUMAN' AND human_user_id IS NOT NULL AND sponsor_user_id IS NULL
 AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL
 AND context_manifest_id IS NULL AND external_credential_id IS NULL AND external_run_id IS NULL
 AND external_agent_id IS NULL)
 OR (actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL
 AND agent_version_id IS NOT NULL AND run_id IS NOT NULL AND session_id IS NOT NULL
 AND context_manifest_id IS NOT NULL AND project_id IS NOT NULL
 AND external_credential_id IS NULL AND external_run_id IS NULL AND external_agent_id IS NULL)
 OR (actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL
 AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL
 AND context_manifest_id IS NULL AND project_id IS NOT NULL
 AND external_credential_id IS NOT NULL AND external_run_id IS NOT NULL)
 OR (actor_kind = 'AGENT' AND human_user_id IS NULL AND sponsor_user_id IS NOT NULL
 AND agent_version_id IS NULL AND run_id IS NULL AND session_id IS NULL
 AND context_manifest_id IS NULL AND external_run_id IS NULL
 AND external_agent_id IS NOT NULL AND external_credential_id IS NOT NULL))
""",
    )
    op.execute(
        "UPDATE external_research_runs SET status = 'REVOKED', "
        "closed_at = CURRENT_TIMESTAMP WHERE status = 'OPEN'"
    )
    op.add_column(
        "artifacts",
        sa.Column(
            "library_destination_revision_id", sa.Uuid(), sa.ForeignKey("object_revisions.id")
        ),
    )
    op.execute("""
CREATE FUNCTION protect_artifact_destination() RETURNS trigger AS $$
BEGIN
 IF NEW.library_destination_revision_id IS DISTINCT FROM OLD.library_destination_revision_id
 THEN RAISE EXCEPTION 'artifact destination is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER artifacts_destination_immutable BEFORE UPDATE ON artifacts
FOR EACH ROW EXECUTE FUNCTION protect_artifact_destination();
""")
    op.create_table(
        "research_activity_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_kind", sa.String(64), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("contribution_id", sa.Uuid(), sa.ForeignKey("contribution_envelopes.id")),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("external_agent_identities.id")),
        sa.Column("sponsor_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column(
            "ownership_scope_id", sa.Uuid(), sa.ForeignKey("research_scopes.id"), nullable=False
        ),
        sa.Column("object_id", sa.Uuid(), sa.ForeignKey("research_objects.id")),
        sa.Column("revision_id", sa.Uuid(), sa.ForeignKey("object_revisions.id")),
        sa.Column("previous_revision_id", sa.Uuid(), sa.ForeignKey("object_revisions.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("reconstructed", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_kind", "source_id", name="uq_research_activity_source"),
    )
    for column in (
        "contribution_id",
        "actor_user_id",
        "agent_id",
        "sponsor_user_id",
        "ownership_scope_id",
        "object_id",
        "revision_id",
    ):
        op.create_index(
            f"ix_research_activity_events_{column}", "research_activity_events", [column]
        )
    op.create_index("ix_research_activity_time", "research_activity_events", ["occurred_at", "id"])
    op.execute(
        "CREATE TRIGGER research_activity_events_immutable BEFORE UPDATE OR DELETE "
        "ON research_activity_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()"
    )


def downgrade() -> None:
    raise RuntimeError("Contribution history requires forward repair; retain immutable provenance")

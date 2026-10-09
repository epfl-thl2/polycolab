"""Add private immutable audit history for credential envelope rewraps."""

from alembic import op

revision = "20260908_credential_rewrap_audit"
down_revision = "20260908_run_artifact_outputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE gateway_credential_rewrap_audit (
 id UUID PRIMARY KEY,
 profile_id UUID NOT NULL REFERENCES gateway_profiles(id),
 credential_version INTEGER NOT NULL,
 source_key_version VARCHAR(200) NOT NULL,
 target_key_version VARCHAR(200) NOT NULL,
 source_fingerprint VARCHAR(64) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL,
 CONSTRAINT uq_gateway_credential_rewrap_target
   UNIQUE (profile_id, credential_version, target_key_version),
 CONSTRAINT ck_gateway_credential_rewrap_fingerprint
   CHECK (length(source_fingerprint) = 64)
)
""")
    op.execute("""
CREATE INDEX ix_gateway_credential_rewrap_audit_profile_id
ON gateway_credential_rewrap_audit(profile_id)
""")
    op.execute("""
CREATE TRIGGER gateway_credential_rewrap_audit_immutable
BEFORE UPDATE OR DELETE ON gateway_credential_rewrap_audit
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation()
""")


def downgrade() -> None:
    raise RuntimeError("Retain credential migration audit history.")

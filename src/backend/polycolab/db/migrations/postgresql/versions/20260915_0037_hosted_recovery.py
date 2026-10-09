"""Hosted completion identity, controller incarnations and durable slot quarantine."""

from alembic import op

revision = "20260915_hosted_recovery"
down_revision = "20260914_hosted_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE hosted_executors DROP CONSTRAINT hosted_executors_capacity_check;
ALTER TABLE hosted_executors ADD CONSTRAINT hosted_executors_capacity_check
CHECK(capacity BETWEEN 0 AND 64);
ALTER TABLE hosted_executors ADD COLUMN incarnation VARCHAR(36) NOT NULL DEFAULT 'legacy';
ALTER TABLE hosted_executors ADD COLUMN protocol_version INTEGER NOT NULL DEFAULT 2;
CREATE TABLE hosted_completions (
 run_id UUID NOT NULL REFERENCES agent_runs(id), generation INTEGER NOT NULL,
 worker_id VARCHAR(200) NOT NULL, payload_digest VARCHAR(64) NOT NULL,
 created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (run_id, generation)
);
CREATE TRIGGER hosted_completion_immutable BEFORE UPDATE OR DELETE ON hosted_completions
FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TABLE hosted_slots (
 worker_id VARCHAR(200) NOT NULL REFERENCES hosted_executors(worker_id),
 ordinal INTEGER NOT NULL, quarantined BOOLEAN NOT NULL DEFAULT FALSE,
 run_id UUID REFERENCES agent_runs(id), generation INTEGER,
 PRIMARY KEY(worker_id, ordinal),
 CHECK(ordinal BETWEEN 0 AND 63), CHECK((run_id IS NULL) = (generation IS NULL))
);
""")


def downgrade() -> None:
    op.execute("DROP TABLE hosted_slots; DROP TABLE hosted_completions")
    op.execute("DELETE FROM hosted_executors WHERE capacity = 0")
    op.execute("ALTER TABLE hosted_executors DROP CONSTRAINT hosted_executors_capacity_check")
    op.execute(
        "ALTER TABLE hosted_executors ADD CONSTRAINT hosted_executors_capacity_check "
        "CHECK(capacity BETWEEN 1 AND 64)"
    )
    op.execute("ALTER TABLE hosted_executors DROP COLUMN incarnation, DROP COLUMN protocol_version")

"""Name key ownership and execution requesters without changing authority or bytes."""

import sqlalchemy as sa
from alembic import op

revision = "20261115_key_names"
down_revision = "20261104_provider_profiles"
branch_labels = None
depends_on = None


def renamed(name: str) -> str:
    for old, new in (
        ("external_agent_credentials", "agent_api_keys"),
        ("external_agent_credential", "agent_api_key"),
        ("external_credential_sponsor", "agent_api_key_owner"),
        ("external_credential_scope", "agent_api_key_scope"),
        ("external_agent_", "agent_api_key_"),
        ("sponsor_user_id", "owner_user_id"),
        ("mutation_count", "write_count"),
        ("max_mutations", "max_writes"),
    ):
        name = name.replace(old, new)
    return name


def upgrade() -> None:
    op.rename_table("external_agent_credentials", "agent_api_keys")
    for old, new in (
        ("sponsor_user_id", "owner_user_id"),
        ("mutation_count", "write_count"),
        ("max_mutations", "max_writes"),
    ):
        op.alter_column("agent_api_keys", old, new_column_name=new)
    op.alter_column(
        "execution_work_items", "sponsor_user_id", new_column_name="requested_by_user_id"
    )
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("agent_api_keys", "execution_work_items"):
        for index in inspector.get_indexes(table):
            if index.get("duplicates_constraint"):
                continue
            name = index["name"]
            target = (
                renamed(name)
                if table == "agent_api_keys"
                else name.replace("sponsor_user_id", "requested_by_user_id")
            )
            if target != name:
                op.drop_index(name, table_name=table)
                op.create_index(target, table, index["column_names"], unique=index["unique"])
    rows = bind.execute(
        sa.text(
            "SELECT conrelid::regclass::text AS tbl, conname FROM pg_constraint "
            "WHERE connamespace=current_schema()::regnamespace "
            "AND conrelid IN ('agent_api_keys'::regclass, 'execution_work_items'::regclass)"
        )
    ).all()
    quote = bind.dialect.identifier_preparer.quote
    for table, name in rows:
        target = (
            renamed(name)
            if table == "agent_api_keys"
            else name.replace("sponsor_user_id", "requested_by_user_id")
        )
        if target != name:
            op.execute(
                f"ALTER TABLE {quote(table)} RENAME CONSTRAINT {quote(name)} TO {quote(target)}"
            )
    op.execute("DROP TRIGGER external_agent_credential_grant_immutable ON agent_api_keys")
    op.execute("DROP FUNCTION external_agent_credential_grant_immutable()")
    op.execute("""
CREATE FUNCTION agent_api_key_grant_immutable() RETURNS trigger AS $$
BEGIN
 IF NEW.project_id IS DISTINCT FROM OLD.project_id
 OR NEW.scope_kind IS DISTINCT FROM OLD.scope_kind
 OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
 OR NEW.token_digest IS DISTINCT FROM OLD.token_digest
 OR NEW.fixed_rights::jsonb IS DISTINCT FROM OLD.fixed_rights::jsonb
 OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
 OR NEW.max_requests IS DISTINCT FROM OLD.max_requests
 OR NEW.max_writes IS DISTINCT FROM OLD.max_writes
 THEN RAISE EXCEPTION 'agent API key grant is immutable'; END IF;
 RETURN NEW;
END; $$ LANGUAGE plpgsql;
CREATE TRIGGER agent_api_key_grant_immutable BEFORE UPDATE ON agent_api_keys
FOR EACH ROW EXECUTE FUNCTION agent_api_key_grant_immutable();
CREATE OR REPLACE FUNCTION validate_execution_work_item() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.agent_run_id IS NOT NULL THEN
   IF NOT EXISTS (
     SELECT 1 FROM agent_runs run
     WHERE run.id = NEW.agent_run_id
       AND run.requested_by_user_id = NEW.requested_by_user_id
       AND run.project_id = NEW.project_id
       AND run.created_at = NEW.queued_at
       AND run.deadline_at IS NOT NULL
   ) THEN RAISE EXCEPTION 'execution agent work identity mismatch'; END IF;
 END IF;
 RETURN NEW;
END $$;
""")


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover database and application backups.")

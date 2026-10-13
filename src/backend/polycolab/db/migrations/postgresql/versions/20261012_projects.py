"""Rename project metadata without rewriting immutable research or retry history."""

from alembic import op

revision = "20261012_projects"
down_revision = "20261012_key_preview"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, constraint, column, check, trigger in (
        (
            "research_scopes",
            "ck_research_scopes_kind_project",
            "scope_kind",
            "(scope_kind = 'COMMONS' AND project_id IS NULL) OR "
            "(scope_kind = 'PROJECT' AND project_id IS NOT NULL)",
            None,
        ),
        (
            "external_agent_credentials",
            "ck_external_credential_scope",
            "scope_kind",
            "(scope_kind = 'ACCOUNT' AND project_id IS NULL) OR "
            "(scope_kind = 'PROJECT' AND project_id IS NOT NULL)",
            "external_agent_credential_grant_immutable",
        ),
        (
            "execution_fairness_states",
            "ck_execution_tenant_kind",
            "tenant_kind",
            "tenant_kind IN ('USER','PROJECT')",
            "execution_fairness_state_write",
        ),
    ):
        op.drop_constraint(constraint, table, type_="check")
        # Only classifications change. Immutable grants, receipts and event JSON stay intact.
        if trigger:
            op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
        op.execute(f"UPDATE {table} SET {column} = 'PROJECT' WHERE {column} = 'WORKSPACE'")
        if trigger:
            op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}")
        op.create_check_constraint(constraint, table, check)
    for table in (
        "workspace_references",
        "workspace_reference_versions",
        "workspace_repositories",
        "workspace_tasks",
    ):
        op.rename_table(table, table.replace("workspace", "project"))

    for table in (
        "project_repositories",
        "project_tasks",
        "repository_mutations",
        "repository_sessions",
    ):
        op.alter_column(table, "workspace_id", new_column_name="project_id")

    # Dependencies track table renames; PL/pgSQL source and object names do not.
    # Run catalog inspection on the server so offline SQL exports work as well.
    op.execute("""
DO $cutover$
DECLARE item RECORD; definition TEXT;
BEGIN
 FOR item IN
   SELECT p.oid::regprocedure::text AS signature, p.proname,
          pg_get_functiondef(p.oid) AS source
   FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname=current_schema() AND p.prokind='f'
 LOOP
   IF lower(item.source) NOT LIKE '%workspace%' THEN CONTINUE; END IF;
   definition := replace(replace(item.source, 'workspace', 'project'), 'WORKSPACE', 'PROJECT');
   IF item.proname LIKE '%workspace%' THEN
     EXECUTE format('ALTER FUNCTION %s RENAME TO %I', item.signature,
                    replace(item.proname, 'workspace', 'project'));
   END IF;
   EXECUTE definition;
 END LOOP;
 FOR item IN
   SELECT conrelid::regclass::text AS tbl, conname AS name FROM pg_constraint
   WHERE connamespace=current_schema()::regnamespace AND conname LIKE '%workspace%'
 LOOP
   EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', item.tbl, item.name,
                  replace(item.name, 'workspace', 'project'));
 END LOOP;
 FOR item IN
   SELECT indexname AS name FROM pg_indexes
   WHERE schemaname=current_schema() AND indexname LIKE '%workspace%'
 LOOP
   EXECUTE format('ALTER INDEX %I RENAME TO %I', item.name,
                  replace(item.name, 'workspace', 'project'));
 END LOOP;
 FOR item IN
   SELECT tgrelid::regclass::text AS tbl, tgname AS name FROM pg_trigger
   WHERE NOT tgisinternal AND tgname LIKE '%workspace%'
     AND tgrelid IN (SELECT oid FROM pg_class
                    WHERE relnamespace=current_schema()::regnamespace)
 LOOP
   EXECUTE format('ALTER TRIGGER %I ON %s RENAME TO %I', item.name, item.tbl,
                  replace(item.name, 'workspace', 'project'));
 END LOOP;
END $cutover$;
""")


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover backup and application version.")

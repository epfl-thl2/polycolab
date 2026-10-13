"""Local project terminology cutover; preserve immutable payloads and identities."""

import sqlalchemy as sa
from alembic import op

revision = "local_20261012_projects"
down_revision = "local_20261012_key_preview"
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    connection = op.get_bind()
    # Batch rebuilding is required for SQLite CHECK/UNIQUE names and classifications.
    for table in (
        "research_scopes",
        "external_agent_credentials",
        "execution_fairness_states",
        "project_references",
        "project_reference_versions",
        "publication_manifests",
        "project_repositories",
        "project_tasks",
        "repository_mutations",
        "repository_sessions",
    ):
        inspector = sa.inspect(connection)
        checks = inspector.get_check_constraints(table)
        with op.batch_alter_table(table) as batch:
            for check in checks:
                if "WORKSPACE" in check["sqltext"]:
                    batch.drop_constraint(check["name"], type_="check")
        column = "tenant_kind" if table == "execution_fairness_states" else "scope_kind"
        if table in ("research_scopes", "external_agent_credentials", "execution_fairness_states"):
            op.execute(f"UPDATE {table} SET {column}='PROJECT' WHERE {column}='WORKSPACE'")
        with op.batch_alter_table(table) as batch:
            for check in checks:
                name = check["name"]
                if "WORKSPACE" in check["sqltext"]:
                    batch.create_check_constraint(
                        name, check["sqltext"].replace("WORKSPACE", "PROJECT")
                    )
                elif name and "workspace" in name:
                    batch.drop_constraint(name, type_="check")
                    batch.create_check_constraint(
                        name.replace("workspace", "project"), check["sqltext"]
                    )
            for unique in inspector.get_unique_constraints(table):
                name = unique["name"]
                if name and "workspace" in name:
                    batch.drop_constraint(name, type_="unique")
                    batch.create_unique_constraint(
                        name.replace("workspace", "project"), unique["column_names"]
                    )
            for foreign in inspector.get_foreign_keys(table):
                name = foreign["name"]
                if name and "workspace" in name:
                    batch.drop_constraint(name, type_="foreignkey")
                    batch.create_foreign_key(
                        name.replace("workspace", "project"),
                        foreign["referred_table"],
                        foreign["constrained_columns"],
                        foreign["referred_columns"],
                    )
        for index in inspector.get_indexes(table):
            name = index["name"]
            if "workspace" in name:
                op.drop_index(name, table_name=table)
                op.create_index(
                    name.replace("workspace", "project"),
                    table,
                    index["column_names"],
                    unique=index["unique"],
                )


def downgrade() -> None:
    raise RuntimeError("Restore the matching pre-cutover local backup and application version.")

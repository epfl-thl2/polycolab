"""Permit public workspaces and transition the Beta dataset to public."""

from alembic import op

revision = "20260909_beta_public_workspaces"
down_revision = "20260909_beta_sample_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_projects_private", "projects", type_="check")
    op.create_check_constraint(
        "ck_projects_visibility",
        "projects",
        "visibility IN ('PRIVATE','PUBLIC')",
    )
    op.execute(
        "UPDATE projects SET visibility = 'PUBLIC' "
        "WHERE id IN (SELECT project_id FROM beta_sample_data_installations)"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE projects SET visibility = 'PRIVATE' "
        "WHERE id IN (SELECT project_id FROM beta_sample_data_installations)"
    )
    op.drop_constraint("ck_projects_visibility", "projects", type_="check")
    op.create_check_constraint(
        "ck_projects_private",
        "projects",
        "visibility = 'PRIVATE'",
    )

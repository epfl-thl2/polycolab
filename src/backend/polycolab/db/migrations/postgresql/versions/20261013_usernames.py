"""Public usernames share the built-in namespace; authentication identities stay stable."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_usernames"
down_revision = "20261012_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(80), nullable=True))
    users = sa.table("users", sa.column("issuer"), sa.column("subject"), sa.column("username"))
    accounts = sa.table("local_accounts", sa.column("id"), sa.column("username"))
    local_name = (
        sa.select(accounts.c.username)
        .where(
            sa.func.replace(sa.cast(accounts.c.id, sa.String), "-", "")
            == sa.func.replace(users.c.subject, "-", "")
        )
        .scalar_subquery()
    )
    op.execute(
        users.update().where(users.c.issuer == "polycolab-local").values(username=local_name)
    )
    op.create_index("uq_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_users_username", table_name="users")
    op.drop_column("users", "username")

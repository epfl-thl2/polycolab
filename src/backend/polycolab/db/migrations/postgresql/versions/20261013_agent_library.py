"""Add the agent library with immutable public history."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_agent_library"
down_revision = "20261013_usernames"
branch_labels = None
depends_on = None


def tables() -> None:
    op.create_table(
        "agent_library_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_version_id", sa.Uuid(), nullable=True),
        sa.Column("source_version_id", sa.Uuid(), nullable=True),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('PROMPT','SKILL','PLUGIN')", name="ck_agent_library_kind"),
        sa.CheckConstraint("revision > 0", name="ck_agent_library_revision"),
    )
    op.create_index(
        "ix_agent_library_entries_owner_user_id", "agent_library_entries", ["owner_user_id"]
    )
    op.create_table(
        "agent_library_drafts",
        sa.Column(
            "entry_id", sa.Uuid(), sa.ForeignKey("agent_library_entries.id"), primary_key=True
        ),
        sa.Column("content", sa.JSON(), nullable=False),
    )
    op.create_table(
        "agent_library_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("agent_library_entries.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("author_name", sa.String(300), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entry_id", "number", name="uq_agent_library_version"),
    )
    op.create_index("ix_agent_library_versions_entry_id", "agent_library_versions", ["entry_id"])
    op.create_table(
        "agent_library_moderation",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entry_id", sa.Uuid(), sa.ForeignKey("agent_library_entries.id"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("hidden", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_agent_library_moderation_entry_id", "agent_library_moderation", ["entry_id"]
    )


def upgrade() -> None:
    tables()
    op.create_foreign_key(
        "fk_agent_library_published",
        "agent_library_entries",
        "agent_library_versions",
        ["published_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_library_source",
        "agent_library_entries",
        "agent_library_versions",
        ["source_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("""CREATE FUNCTION agent_library_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'agent library history is immutable'; END; $$""")
    for table in ("agent_library_versions", "agent_library_moderation"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION agent_library_immutable()"
        )
    op.execute("""CREATE FUNCTION agent_library_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
            OR NEW.kind IS DISTINCT FROM OLD.kind
            OR NEW.source_version_id IS DISTINCT FROM OLD.source_version_id
            OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'agent library identity is immutable';
        END IF;
        RETURN NEW;
        END; $$""")
    op.execute(
        "CREATE TRIGGER agent_library_identity BEFORE UPDATE ON agent_library_entries "
        "FOR EACH ROW EXECUTE FUNCTION agent_library_identity()"
    )


def downgrade() -> None:
    raise RuntimeError("Restore a verified backup instead of deleting published history.")

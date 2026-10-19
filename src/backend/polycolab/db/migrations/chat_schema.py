"""Frozen DDL shared by the PostgreSQL and SQLite direct-chat revisions."""

import sqlalchemy as sa
from alembic import op


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("active_request_id", sa.Uuid(), nullable=True),
        sa.Column("active_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])
    op.create_index("ix_chat_conversations_project_id", "chat_conversations", ["project_id"])
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("chat_conversations.id"), nullable=False
        ),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("gateway_profiles.id"), nullable=False),
        sa.Column("model_id", sa.String(500), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False),
        sa.Column("response_md", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_chat_turn_request"),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_chat_turn_sequence"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')", name="ck_chat_turn_status"
        ),
    )
    op.create_index("ix_chat_turns_conversation_id", "chat_turns", ["conversation_id"])

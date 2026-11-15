"""Canonical model inputs for local and API-backed hosted execution."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.agents.conversations import ConversationNotFound
from polycolab.db.converters.conversation import agent_message
from polycolab.db.models import (
    SqlAgentRun,
    SqlConversation,
    SqlConversationItem,
    SqlPlatformAgentVersion,
)


def model_messages(session: Session, run: SqlAgentRun) -> list[dict[str, object]]:
    agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
    parent = session.get(SqlConversation, run.conversation_id)
    if agent is None or parent is None or parent.agent_version_id != agent.id:
        raise ConversationNotFound
    result: list[dict[str, object]] = [{"role": "system", "content": agent.instructions_text}]
    if parent.system_prompt:
        result.append({"role": "system", "content": parent.system_prompt})
    for message in session.scalars(
        select(SqlConversationItem)
        .where(
            SqlConversationItem.conversation_id == run.conversation_id,
            SqlConversationItem.item_type == "message",
            SqlConversationItem.visibility == "user_visible",
            SqlConversationItem.sequence <= run.input_message_sequence,
        )
        .order_by(SqlConversationItem.sequence)
    ):
        item = agent_message(
            message, agent_version_id=agent.id, agent_display_name=agent.display_name
        )
        result.append({"role": item.data.role.value, "content": item.data.content_md})
    return result

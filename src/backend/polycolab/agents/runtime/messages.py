"""Canonical model inputs for local and API-backed hosted execution."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.agents.grants import requested
from polycolab.agents.sessions import SessionNotFound
from polycolab.db.models import (
    SqlAgentMessage,
    SqlAgentRun,
    SqlAgentSession,
    SqlPlatformAgentVersion,
)
from polycolab.entities.enums import AgentMessageRole


def model_messages(session: Session, run: SqlAgentRun) -> list[dict[str, object]]:
    agent = session.get(SqlPlatformAgentVersion, run.agent_version_id)
    parent = session.get(SqlAgentSession, run.session_id)
    if agent is None or parent is None or parent.agent_version_id != agent.id:
        raise SessionNotFound
    result: list[dict[str, object]] = [{"role": "system", "content": agent.instructions_text}]
    if parent.system_prompt:
        result.append({"role": "system", "content": parent.system_prompt})
    authority = requested(session, run.id)
    if authority is not None and authority.destination == "PUBLIC":
        result.append({"role": "user", "content": authority.public_task_md})
        return result
    for message in session.scalars(
        select(SqlAgentMessage)
        .where(
            SqlAgentMessage.session_id == run.session_id,
            SqlAgentMessage.sequence <= run.input_message_sequence,
        )
        .order_by(SqlAgentMessage.sequence)
    ):
        role = {
            AgentMessageRole.USER: "user",
            AgentMessageRole.AGENT: "assistant",
            AgentMessageRole.SYSTEM: "system",
        }[message.role]
        result.append({"role": role, "content": message.content_md})
    return result

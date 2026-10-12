"""Advertise execution only while a compatible hosted executor is ready."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.models import SqlHostedExecutor
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings

router = APIRouter(prefix="/api/v1")


class AgentCapabilities(BaseModel):
    sessions: bool
    execution_available: bool
    hosted_agents: bool
    verification: bool = False


def hosted_ready(session: Session, settings: Settings) -> bool:
    if not settings.feature_agent_execution_enabled or not settings.runtime_codex_image:
        return False
    return (
        settings.hosted_agent_capacity > 0
        and session.scalar(
            select(SqlHostedExecutor.worker_id)
            .where(
                SqlHostedExecutor.image_digest
                == settings.runtime_codex_image.rsplit("@sha256:", 1)[-1],
                SqlHostedExecutor.expires_at > utc_now(),
                SqlHostedExecutor.capacity > 0,
                SqlHostedExecutor.protocol_version == 4,
            )
            .limit(1)
        )
        is not None
    )


@router.get(
    "/agent-capabilities", response_model=AgentCapabilities, operation_id="getAgentCapabilities"
)
def capabilities(request: Request, db: DbSession, user: CurrentUser) -> AgentCapabilities:
    settings = request.app.state.settings
    ready = hosted_ready(db, settings)
    return AgentCapabilities(
        execution_available=settings.feature_agent_execution_enabled
        and (settings.runtime_codex_image is None or ready),
        sessions=request.app.state.settings.feature_agent_execution_enabled,
        hosted_agents=ready,
    )

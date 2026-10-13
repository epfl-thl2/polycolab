"""Owner-private session authorization shared by routes and execution services."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectNotFound,
    project_policy,
)
from polycolab.db.models import SqlAgentRun, SqlAgentSession
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import ProjectRole


def _session_scope(
    db: Session, *, session_id: UUID, user_id: UUID, action: ProjectAction
) -> SqlAgentSession:
    value = db.get(SqlAgentSession, session_id)
    if value is None:
        raise ProjectNotFound
    scope = project_policy.require_scope(
        SqlAlchemyTransaction(db), value.project_id, user_id, ProjectAction.VIEW
    )
    shared_view = action is ProjectAction.VIEW and value.is_shared
    if scope.membership.role is ProjectRole.READ_ONLY and not shared_view:
        raise AuthorizationDenied
    # Sessions are private to their creator. Deliberately conceal another
    # member's chat, including from project owners, rather than leaking it.
    if value.created_by_user_id != user_id and not shared_view:
        raise ProjectNotFound
    if action is ProjectAction.RUN_AGENTS:
        project_policy.require_scope(SqlAlchemyTransaction(db), value.project_id, user_id, action)
    return value


def _run_scope(db: Session, *, run_id: UUID, user_id: UUID, action: ProjectAction) -> SqlAgentRun:
    run = db.get(SqlAgentRun, run_id)
    if run is None:
        raise ProjectNotFound
    parent = _session_scope(db, session_id=run.session_id, user_id=user_id, action=action)
    # This check protects historical or malformed rows as well as the normal
    # route path, which only permits the session creator to queue a turn.
    if (
        run.requested_by_user_id != user_id
        and not (action is ProjectAction.VIEW and parent.is_shared)
    ) or parent.project_id != run.project_id:
        raise ProjectNotFound
    return run

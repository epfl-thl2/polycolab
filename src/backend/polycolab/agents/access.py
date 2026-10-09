"""Owner-private session authorization shared by routes and execution services."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    AuthorizationDenied,
    WorkspaceAction,
    WorkspaceNotFound,
    workspace_policy,
)
from polycolab.db.models import SqlAgentRun, SqlAgentSession
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import WorkspaceRole


def _session_scope(
    db: Session, *, session_id: UUID, user_id: UUID, action: WorkspaceAction
) -> SqlAgentSession:
    value = db.get(SqlAgentSession, session_id)
    if value is None:
        raise WorkspaceNotFound
    scope = workspace_policy.require_scope(
        SqlAlchemyTransaction(db), value.project_id, user_id, WorkspaceAction.VIEW
    )
    if scope.membership.role is WorkspaceRole.READ_ONLY:
        raise AuthorizationDenied
    # Sessions are private to their creator. Deliberately conceal another
    # member's chat, including from project owners, rather than leaking it.
    if value.created_by_user_id != user_id:
        raise WorkspaceNotFound
    if action is WorkspaceAction.RUN_AGENTS:
        workspace_policy.require_scope(SqlAlchemyTransaction(db), value.project_id, user_id, action)
    return value


def _run_scope(db: Session, *, run_id: UUID, user_id: UUID, action: WorkspaceAction) -> SqlAgentRun:
    run = db.get(SqlAgentRun, run_id)
    if run is None:
        raise WorkspaceNotFound
    parent = _session_scope(db, session_id=run.session_id, user_id=user_id, action=action)
    # This check protects historical or malformed rows as well as the normal
    # route path, which only permits the session creator to queue a turn.
    if run.requested_by_user_id != user_id or parent.project_id != run.project_id:
        raise WorkspaceNotFound
    return run

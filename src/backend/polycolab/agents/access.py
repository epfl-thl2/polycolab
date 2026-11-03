"""SQL composition of session policy for existing execution consumers."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectAction, ProjectNotFound
from polycolab.conversations.service import require_read, require_submit
from polycolab.db.models import SqlAgentRun, SqlConversation
from polycolab.db.transaction import SqlAlchemyTransaction


def _session_scope(
    db: Session, *, session_id: UUID, user_id: UUID, action: ProjectAction
) -> SqlConversation:
    value = db.get(SqlConversation, session_id)
    if value is None:
        raise ProjectNotFound
    if action is ProjectAction.RUN_AGENTS:
        require_submit(SqlAlchemyTransaction(db), session_id, user_id)
    else:
        require_read(SqlAlchemyTransaction(db), session_id, user_id)
    return value


def _run_scope(db: Session, *, run_id: UUID, user_id: UUID, action: ProjectAction) -> SqlAgentRun:
    run = db.get(SqlAgentRun, run_id)
    if run is None:
        raise ProjectNotFound
    parent = _session_scope(db, session_id=run.session_id, user_id=user_id, action=action)
    # Mutating or reusing a run's inputs remains restricted to its sender.
    # Interruption has a separate policy allowing the session owner too.
    if (
        action is not ProjectAction.VIEW and run.requested_by_user_id != user_id
    ) or parent.project_id != run.project_id:
        raise ProjectNotFound
    return run

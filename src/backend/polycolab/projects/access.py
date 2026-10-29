"""Current project authority for services using a SQLAlchemy session."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.projects import ProjectMemberAccess


def project_access(
    session: Session, project_id: UUID, user_id: UUID, *, write: bool = False
) -> ProjectMemberAccess:
    return project_policy.require_scope(
        SqlAlchemyTransaction(session),
        project_id,
        user_id,
        ProjectAction.WRITE_FILES if write else ProjectAction.VIEW,
    )

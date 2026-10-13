"""Construct linear and archived Git services from deployment adapters."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.db.stores.repositories import SqlRepositoryStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.git_storage import GitRepository
from polycolab.projects.linear_service import CollaborationClient, LinearService
from polycolab.projects.repository_service import RepositoryService


def service(settings: Settings, db: Session, project_id: UUID, user_id: UUID) -> LinearService:
    if settings.project_repository_directory is None:
        raise RepositoryError("repository_disabled", 503)
    return LinearService(
        SqlAlchemyTransaction(db),
        GitRepository(
            settings.project_repository_directory, project_id, settings.project_repository_max_bytes
        ),
        project_id,
        user_id,
        CollaborationClient(
            settings.collaboration_url, settings.collaboration_token.get_secret_value()
        ),
    )


def repository_service(
    settings: Settings, db: Session, project_id: UUID, user_id: UUID
) -> RepositoryService:
    if settings.project_repository_directory is None:
        raise RepositoryError("repository_disabled", 503)
    return RepositoryService(
        SqlAlchemyTransaction(db),
        SqlRepositoryStore(db),
        GitRepository(
            settings.project_repository_directory, project_id, settings.project_repository_max_bytes
        ),
        project_id,
        user_id,
    )

"""Member and public project projections."""

from uuid import UUID

from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectNotFound, project_policy
from polycolab.db.models import SqlMembership, SqlProject
from polycolab.entities.projects import Membership as MembershipEntity
from polycolab.entities.projects import Project as ProjectEntity
from polycolab.projects.schemas import ProjectMemberRead, PublicProjectRead


def _member_read(
    project: SqlProject | ProjectEntity,
    membership: SqlMembership | MembershipEntity,
    member_count: int,
) -> ProjectMemberRead:
    return ProjectMemberRead(
        workspace_mode=(
            "default"
            if project.workspace_mode == "default"
            else "linear"
            if project.workspace_mode == "linear"
            else "git"
        ),
        id=project.id,
        name=project.name,
        description=project.description,
        visibility=project.visibility,
        archived_at=project.archived_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
        current_user_role=membership.role,
        member_count=member_count,
    )


def _public_project_read(project: SqlProject | ProjectEntity) -> PublicProjectRead:
    return PublicProjectRead(
        id=project.id,
        name=project.name,
        description=project.description,
        visibility=project.visibility,
        archived_at=project.archived_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _public_project(session: Session, project_id: UUID) -> SqlProject:
    project = session.get(SqlProject, project_id)
    if not project_policy.can_read_public(project):
        raise ProjectNotFound
    assert project is not None
    return project

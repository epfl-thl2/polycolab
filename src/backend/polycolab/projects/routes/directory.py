"""Project directory and metadata reads."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import select

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.app.access import Access, ResourceAccess
from polycolab.app.cursors import Pagination
from polycolab.app.dependencies import DbSession, RequestTransaction
from polycolab.db.models import SqlMembership, SqlProject
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.projects import Project as ProjectEntity
from polycolab.projects import projections
from polycolab.projects.schemas import ProjectCollection, ProjectMemberRead, PublicProjectRead
from polycolab.projects.service import count_visible, list_visible, member_counts

router = APIRouter(prefix="/api/v1", tags=["projects"])
ProjectView = ProjectMemberRead | PublicProjectRead


def member(session: DbSession, access: ResourceAccess, project_id: UUID) -> SqlMembership | None:
    if access.user_id is None:
        return None
    return session.scalar(
        select(SqlMembership).where(
            SqlMembership.project_id == project_id, SqlMembership.user_id == access.user_id
        )
    )


def project(
    session: DbSession, access: ResourceAccess, project_id: UUID
) -> tuple[SqlProject | ProjectEntity, bool]:
    membership = member(session, access, project_id)
    if membership:
        scope = project_policy.require_scope(
            SqlAlchemyTransaction(session), project_id, membership.user_id, ProjectAction.VIEW
        )
        return scope.project, True
    return projections._public_project(session, project_id), False


@router.get("/projects", response_model=ProjectCollection, operation_id="listProjects")
def projects(
    transaction: RequestTransaction,
    access: Access,
    page: Pagination,
    scope: Literal["public", "member"] = "public",
    q: Annotated[str | None, Query(max_length=500)] = None,
    category: Literal["active", "owned", "shared", "archived"] | None = None,
    sort: Literal["updated", "name", "name_desc", "relevance"] = "updated",
) -> ProjectCollection:
    if scope == "member":
        access.require_user_id()
    cursor_scope = f"projects:{scope}:{access.user_id}:{q}:{category}:{sort}"
    rows = list_visible(
        transaction,
        user_id=access.user_id,
        members_only=scope == "member",
        query=q,
        category=category,
        sort=sort,
        after=page.after_uuid(scope=cursor_scope),
        limit=page.limit + 1,
    )
    selected = rows[: page.limit]
    counts = member_counts(transaction, [row.project.id for row in selected if row.membership])
    return ProjectCollection(
        total=count_visible(
            transaction,
            user_id=access.user_id,
            members_only=scope == "member",
            query=q,
            category=category,
        ),
        items=[
            projections._member_read(row.project, row.membership, counts[row.project.id])
            if row.membership
            else projections._public_project_read(row.project)
            for row in selected
        ],
        next_cursor=page.next_uuid(selected[-1].project.id, scope=cursor_scope)
        if len(rows) > page.limit
        else None,
    )


@router.get("/projects/{project_id}", response_model=ProjectView, operation_id="getProject")
def get_project(project_id: UUID, session: DbSession, access: Access) -> ProjectView:
    row, _ = project(session, access, project_id)
    membership = member(session, access, project_id)
    return (
        projections._member_read(
            row, membership, member_counts(SqlAlchemyTransaction(session), [row.id])[row.id]
        )
        if membership
        else projections._public_project_read(row)
    )

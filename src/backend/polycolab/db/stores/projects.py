"""Project SQL operations; callers own policy and transaction completion."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, SQLColumnExpression, and_, case, func, or_, select, true
from sqlalchemy.orm import Session

from polycolab.db.converters import projects as converter
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import (
    SqlExternalResearchRun,
    SqlInvitation,
    SqlMembership,
    SqlProject,
    SqlResearchScope,
)
from polycolab.entities.enums import (
    InvitationStatus,
    ProjectRole,
    ProjectVisibility,
    ResearchScopeKind,
)
from polycolab.entities.projects import (
    Invitation,
    Membership,
    Project,
    ProjectAccess,
)
from polycolab.entities.time import utc_now


class SqlProjectStore:
    @persistence_boundary
    def member_counts(self, project_ids: list[UUID]) -> dict[UUID, int]:
        if not project_ids:
            return {}
        rows = self._session.execute(
            select(SqlMembership.project_id, func.count(SqlMembership.id))
            .where(SqlMembership.project_id.in_(project_ids))
            .group_by(SqlMembership.project_id)
        )
        return {project_id: count for project_id, count in rows}

    def __init__(self, session: Session) -> None:
        self._session = session

    @persistence_boundary
    def list_visible(
        self,
        *,
        user_id: UUID | None,
        members_only: bool,
        query: str | None,
        after: UUID | None,
        limit: int,
        category: str | None = None,
        sort: str = "updated",
    ) -> tuple[ProjectAccess, ...]:
        statement = self._visible_statement(
            user_id=user_id, members_only=members_only, query=query, category=category
        )
        if sort in {"name", "name_desc"}:
            key = func.lower(SqlProject.name)
            anchor = (
                select(func.lower(SqlProject.name)).where(SqlProject.id == after).scalar_subquery()
            )
            descending = sort == "name_desc"
            order: list[SQLColumnExpression[Any]] = [
                key.desc() if descending else key,
                SqlProject.id,
            ]
            if after is not None:
                statement = statement.where(
                    or_(
                        key < anchor if descending else key > anchor,
                        and_(key == anchor, SqlProject.id > after),
                    )
                )
        else:
            updated_key = SqlProject.updated_at
            anchor = select(SqlProject.updated_at).where(SqlProject.id == after).scalar_subquery()
            tail = (
                or_(updated_key < anchor, and_(updated_key == anchor, SqlProject.id > after))
                if after is not None
                else true()
            )
            order = [updated_key.desc(), SqlProject.id]
            if sort == "relevance" and query:
                rank = case(
                    (func.lower(SqlProject.name) == query.lower(), 0),
                    (SqlProject.name.istartswith(query, autoescape=True), 1),
                    (SqlProject.name.icontains(query, autoescape=True), 2),
                    else_=3,
                )
                rank_anchor = select(rank).where(SqlProject.id == after).scalar_subquery()
                order = [rank, *order]
                tail = or_(rank > rank_anchor, and_(rank == rank_anchor, tail))
            if after is not None:
                statement = statement.where(tail)
        return tuple(
            ProjectAccess(
                converter.project(project), converter.membership(member) if member else None
            )
            for project, member in self._session.execute(statement.order_by(*order).limit(limit))
        )

    def _visible_statement(
        self,
        *,
        user_id: UUID | None,
        members_only: bool,
        query: str | None,
        category: str | None,
    ) -> Select[tuple[SqlProject, SqlMembership]]:
        statement = (
            select(SqlProject, SqlMembership)
            .outerjoin(
                SqlMembership,
                (SqlMembership.project_id == SqlProject.id) & (SqlMembership.user_id == user_id),
            )
            .where(SqlProject.deleted_at.is_(None))
        )
        if members_only:
            statement = statement.where(SqlMembership.id.is_not(None))
        else:
            statement = statement.where(
                SqlProject.visibility == ProjectVisibility.PUBLIC,
                SqlProject.archived_at.is_(None),
            )
        if members_only and category:
            statement = statement.where(
                SqlProject.archived_at.is_not(None)
                if category == "archived"
                else SqlProject.archived_at.is_(None)
            )
            if category == "owned":
                statement = statement.where(SqlMembership.role == ProjectRole.OWNER)
            elif category == "shared":
                statement = statement.where(SqlMembership.role != ProjectRole.OWNER)
        if query:
            statement = statement.where(
                or_(
                    SqlProject.name.icontains(query, autoescape=True),
                    SqlProject.description.icontains(query, autoescape=True),
                )
            )
        return statement

    @persistence_boundary
    def count_visible(
        self,
        *,
        user_id: UUID | None,
        members_only: bool,
        query: str | None,
        category: str | None = None,
    ) -> int:
        statement = self._visible_statement(
            user_id=user_id, members_only=members_only, query=query, category=category
        )
        return self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0

    @persistence_boundary
    def project(self, project_id: UUID, *, lock: bool = False) -> Project | None:
        statement = select(SqlProject).where(SqlProject.id == project_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = self._session.scalar(statement)
        return converter.project(row) if row is not None else None

    @persistence_boundary
    def membership(
        self, project_id: UUID, user_id: UUID, *, lock: bool = False
    ) -> Membership | None:
        statement = select(SqlMembership).where(
            SqlMembership.project_id == project_id, SqlMembership.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = self._session.scalar(statement)
        return converter.membership(row) if row is not None else None

    @persistence_boundary
    def update_settings(
        self,
        project_id: UUID,
        *,
        name: str,
        description: str | None,
        visibility: ProjectVisibility,
        archived_at: datetime | None,
    ) -> Project:
        row = self._session.get(SqlProject, project_id)
        if row is None:
            raise LookupError("project disappeared during settings update")
        row.name = name
        row.description = description
        row.visibility = visibility
        row.archived_at = archived_at
        self._session.flush()
        return converter.project(row)

    @persistence_boundary
    def mark_deleted(self, project_id: UUID, *, at: datetime) -> None:
        row = self._session.get(SqlProject, project_id)
        if row is None:
            raise LookupError("project disappeared during deletion")
        row.deleted_at = at
        self._session.flush()

    @persistence_boundary
    def owners(self, project_id: UUID) -> tuple[Membership, ...]:
        return tuple(
            converter.membership(row)
            for row in self._session.scalars(
                select(SqlMembership)
                .where(
                    SqlMembership.project_id == project_id,
                    SqlMembership.role == ProjectRole.OWNER,
                )
                .with_for_update()
            )
        )

    @persistence_boundary
    def create_project(
        self,
        *,
        creator_id: UUID,
        name: str,
        description: str | None,
        visibility: ProjectVisibility,
    ) -> Project:
        row = SqlProject(
            name=name, description=description, visibility=visibility, created_by_user_id=creator_id
        )
        self._session.add(row)
        self._session.flush()
        self._session.add(SqlResearchScope(project_id=row.id, scope_kind=ResearchScopeKind.PROJECT))
        self._session.add(
            SqlMembership(project_id=row.id, user_id=creator_id, role=ProjectRole.OWNER)
        )
        self._session.flush()
        return converter.project(row)

    @persistence_boundary
    def add_membership(
        self, *, project_id: UUID, user_id: UUID, role: ProjectRole, invited_by: UUID | None
    ) -> Membership:
        row = SqlMembership(
            project_id=project_id, user_id=user_id, role=role, invited_by_user_id=invited_by
        )
        self._session.add(row)
        self._session.flush()
        return converter.membership(row)

    @persistence_boundary
    def change_role(self, membership_id: UUID, role: ProjectRole) -> Membership:
        row = self._session.get(SqlMembership, membership_id)
        if row is None:
            raise LookupError("membership disappeared during mutation")
        row.role = role
        self._session.flush()
        return converter.membership(row)

    @persistence_boundary
    def remove_membership(self, membership_id: UUID) -> None:
        row = self._session.get(SqlMembership, membership_id)
        if row is None:
            raise LookupError("membership disappeared during mutation")
        self._session.delete(row)
        self._session.flush()

    @persistence_boundary
    def close_external_runs(self, project_id: UUID, user_id: UUID) -> None:
        for row in self._session.scalars(
            select(SqlExternalResearchRun).where(
                SqlExternalResearchRun.project_id == project_id,
                SqlExternalResearchRun.sponsor_user_id == user_id,
                SqlExternalResearchRun.status == "OPEN",
            )
        ):
            row.status = "REVOKED"
            row.closed_at = utc_now()
        self._session.flush()

    @persistence_boundary
    def create_invitation(
        self,
        *,
        project_id: UUID,
        email: str,
        role: ProjectRole,
        token_digest: str,
        invited_by: UUID,
        expires_at: datetime,
    ) -> Invitation:
        row = SqlInvitation(
            project_id=project_id,
            email=email,
            role=role,
            token_digest=token_digest,
            invited_by_user_id=invited_by,
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return converter.invitation(row)

    @persistence_boundary
    def invitation_by_digest(self, digest: str) -> Invitation | None:
        row = self._session.scalar(
            select(SqlInvitation).where(SqlInvitation.token_digest == digest).with_for_update()
        )
        return converter.invitation(row) if row is not None else None

    @persistence_boundary
    def revoke_invitation(self, invitation_id: UUID, *, at: datetime) -> None:
        row = self._session.get(SqlInvitation, invitation_id)
        if row is None:
            raise LookupError("invitation disappeared during revocation")
        row.status = InvitationStatus.REVOKED
        row.revoked_at = at
        self._session.flush()

    @persistence_boundary
    def accept_invitation(self, invitation_id: UUID, *, user_id: UUID, at: datetime) -> None:
        row = self._session.get(SqlInvitation, invitation_id)
        if row is None:
            raise LookupError("invitation disappeared during acceptance")
        row.status = InvitationStatus.ACCEPTED
        row.accepted_by_user_id = user_id
        row.accepted_at = at
        self._session.flush()

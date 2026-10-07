"""Resolve authorized scopes for shared reads without trusting request scope IDs."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from polycolab.app.access import ResearchAccess
from polycolab.db.models import SqlObjectRevision
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import project_access, public_revision


def collection_scope(
    session: Session, access: ResearchAccess, scope: str, project_id: UUID | None
) -> UUID | None:
    if scope == "public":
        if project_id is not None:
            raise HTTPException(422, "project_id requires member scope")
        return None
    user_id = access.require_user_id()
    if project_id is None:
        raise HTTPException(422, "member scope requires project_id")
    project_access(session, project_id, user_id)
    return project_id


def revision_scope(
    session: Session, access: ResearchAccess, revision_id: UUID, project_id: UUID | None = None
) -> UUID | None:
    from sqlalchemy import select

    from polycolab.db.models import SqlMembership

    revision = session.get(SqlObjectRevision, revision_id)
    if revision is None or (project_id is not None and project_id != revision.project_id):
        raise ResearchNotFound
    if project_id is not None:
        project_access(session, project_id, access.require_user_id())
    if (
        revision.project_id
        and access.user_id
        and session.scalar(
            select(SqlMembership.id).where(
                SqlMembership.project_id == revision.project_id,
                SqlMembership.user_id == access.user_id,
            )
        )
    ):
        project_access(session, revision.project_id, access.user_id)
        return revision.project_id
    public_revision(session, revision_id)
    return None

"""Shared public, member, and delegated-agent research HTTP resources."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from polycolab.access.authorization import WorkspaceAction, workspace_policy
from polycolab.app.access import Access, ResearchAccess
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import DbSession, RequestTransaction
from polycolab.db.models import (
    SqlMembership,
    SqlObjectRevision,
    SqlProject,
    SqlRelationAssertion,
    SqlResearchActivityEvent,
    SqlResearchComment,
    SqlResearchObject,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.object_kinds import ObjectKind
from polycolab.entities.workspaces import Workspace as WorkspaceEntity
from polycolab.research.history import visible_query
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import public_condition
from polycolab.research.schemas import (
    CommentRead,
    PublicCommentRead,
    PublicRevisionRead,
    RevisionRead,
)
from polycolab.research.version_projections import object_read, relationship_reads, version_reads
from polycolab.research.version_schemas import (
    ObjectVersionRead,
    ObjectVersionRelationshipRead,
    VersionedObjectRead,
)
from polycolab.workspaces.routes import workspace as human
from polycolab.workspaces.schemas import (
    PublicWorkspaceRead,
    WorkspaceCollection,
    WorkspaceMemberRead,
)
from polycolab.workspaces.service import count_visible, list_visible, member_counts

router = APIRouter(prefix="/api/v1", tags=["research"])
ObjectView = VersionedObjectRead
RevisionView = RevisionRead | PublicRevisionRead
RelationView = ObjectVersionRelationshipRead
CommentView = CommentRead | PublicCommentRead
WorkspaceView = WorkspaceMemberRead | PublicWorkspaceRead


def member(session: DbSession, access: ResearchAccess, workspace_id: UUID) -> SqlMembership | None:
    if access.user_id is None:
        return None
    return session.scalar(
        select(SqlMembership).where(
            SqlMembership.project_id == workspace_id, SqlMembership.user_id == access.user_id
        )
    )


def workspace(
    session: DbSession, access: ResearchAccess, workspace_id: UUID
) -> tuple[SqlProject | WorkspaceEntity, bool]:
    membership = member(session, access, workspace_id)
    if membership:
        scope = workspace_policy.require_scope(
            SqlAlchemyTransaction(session), workspace_id, membership.user_id, WorkspaceAction.VIEW
        )
        return scope.workspace, True
    return human._public_project(session, workspace_id), False


def object_scope(
    session: DbSession, access: ResearchAccess, object_id: UUID
) -> tuple[SqlResearchObject, bool]:
    obj = session.get(SqlResearchObject, object_id)
    if obj is None:
        raise ResearchNotFound
    if member(session, access, obj.project_id):
        workspace(session, access, obj.project_id)
        return obj, True
    if not session.scalar(
        select(SqlObjectRevision.id)
        .where(SqlObjectRevision.object_id == obj.id, public_condition(SqlObjectRevision.id))
        .limit(1)
    ):
        raise ResearchNotFound
    return obj, False


@router.get("/workspaces", response_model=WorkspaceCollection, operation_id="listWorkspaces")
def workspaces(
    transaction: RequestTransaction,
    access: Access,
    page: Pagination,
    scope: Literal["public", "member"] = "public",
    q: Annotated[str | None, Query(max_length=500)] = None,
    category: Literal["active", "owned", "shared", "archived"] | None = None,
    sort: Literal["updated", "name", "name_desc", "relevance"] = "updated",
) -> WorkspaceCollection:
    if scope == "member":
        access.require_user_id()
    cursor_scope = f"workspaces:{scope}:{access.user_id}:{q}:{category}:{sort}"
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
    counts = member_counts(transaction, [row.workspace.id for row in selected if row.membership])
    return WorkspaceCollection(
        total=count_visible(
            transaction,
            user_id=access.user_id,
            members_only=scope == "member",
            query=q,
            category=category,
        ),
        items=[
            human._member_read(row.workspace, row.membership, counts[row.workspace.id])
            if row.membership
            else human._public_project_read(row.workspace)
            for row in selected
        ],
        next_cursor=page.next_uuid(selected[-1].workspace.id, scope=cursor_scope)
        if len(rows) > page.limit
        else None,
    )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView, operation_id="getWorkspace")
def get_workspace(workspace_id: UUID, session: DbSession, access: Access) -> WorkspaceView:
    row, _ = workspace(session, access, workspace_id)
    membership = member(session, access, workspace_id)
    return (
        human._member_read(
            row, membership, member_counts(SqlAlchemyTransaction(session), [row.id])[row.id]
        )
        if membership
        else human._public_project_read(row)
    )


@router.get(
    "/workspaces/{workspace_id}/objects",
    response_model=Collection[ObjectView],
    operation_id="listResearchObjects",
)
def objects(
    workspace_id: UUID,
    session: DbSession,
    access: Access,
    page: Pagination,
    kind: ObjectKind | None = None,
) -> Collection[ObjectView]:
    _, private = workspace(session, access, workspace_id)
    query = select(SqlResearchObject).where(SqlResearchObject.project_id == workspace_id)
    if not private:
        query = query.where(
            SqlResearchObject.id.in_(
                select(SqlObjectRevision.object_id).where(public_condition(SqlObjectRevision.id))
            )
        )
    if kind:
        query = query.where(SqlResearchObject.canonical_kind == kind)
    rows, cursor = page.select(
        session,
        query,
        SqlResearchObject.id,
        scope=f"objects:{workspace_id}:{access.user_id}:{kind}",
    )
    return Collection(
        items=[object_read(session, row, public=not private) for row in rows],
        next_cursor=cursor,
    )


@router.get("/objects/{object_id}", response_model=ObjectView, operation_id="getResearchObject")
def get_object(object_id: UUID, session: DbSession, access: Access) -> ObjectView:
    row, private = object_scope(session, access, object_id)
    return object_read(session, row, public=not private)


@router.get(
    "/objects/{object_id}/versions",
    response_model=Collection[ObjectVersionRead],
    operation_id="listObjectVersions",
)
def revisions(
    object_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[ObjectVersionRead]:
    obj, private = object_scope(session, access, object_id)
    query = select(SqlObjectRevision).where(SqlObjectRevision.object_id == object_id)
    if not private:
        query = query.where(public_condition(SqlObjectRevision.id))
    rows, cursor = page.select(
        session,
        query,
        SqlObjectRevision.number,
        scope=f"versions:{object_id}:{access.user_id}",
        descending=True,
    )
    return Collection(
        items=version_reads(session, rows, project_id=obj.project_id, public=not private),
        next_cursor=cursor,
    )


@router.get(
    "/objects/{object_id}/comments",
    response_model=Collection[CommentView],
    operation_id="listObjectComments",
)
def comments(
    object_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[CommentView]:
    _, private = object_scope(session, access, object_id)
    query = select(SqlResearchComment).where(SqlResearchComment.object_id == object_id)
    if not private:
        query = query.where(
            SqlResearchComment.id.in_(
                visible_query(access, "public")
                .where(SqlResearchActivityEvent.source_kind == "ResearchComment")
                .with_only_columns(SqlResearchActivityEvent.source_id)
            )
        )
    rows, cursor = page.select(
        session, query, SqlResearchComment.id, scope=f"comments:{object_id}:{access.user_id}"
    )
    return Collection(
        items=[
            human._comment_read(session, row)
            if private
            else human._public_comment_read(session, row)
            for row in rows
        ],
        next_cursor=cursor,
    )


@router.get(
    "/objects/{object_id}/relations",
    response_model=Collection[RelationView],
    operation_id="listObjectRelations",
)
def relations(
    object_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[RelationView]:
    obj, private = object_scope(session, access, object_id)
    revisions = select(SqlObjectRevision.id).where(SqlObjectRevision.object_id == object_id)
    query = select(SqlRelationAssertion).where(
        or_(
            SqlRelationAssertion.source_revision_id.in_(revisions),
            SqlRelationAssertion.target_revision_id.in_(revisions),
        )
    )
    public_ids = (
        visible_query(access, "public")
        .where(SqlResearchActivityEvent.source_kind == "RelationAssertion")
        .with_only_columns(SqlResearchActivityEvent.source_id)
    )
    visible: ColumnElement[bool] = SqlRelationAssertion.id.in_(public_ids)
    if private:
        member_ids = (
            visible_query(access, "member")
            .where(SqlResearchActivityEvent.source_kind == "RelationAssertion")
            .with_only_columns(SqlResearchActivityEvent.source_id)
        )
        visible = or_(visible, SqlRelationAssertion.id.in_(member_ids))
    query = query.where(visible)
    rows, cursor = page.select(
        session, query, SqlRelationAssertion.id, scope=f"relations:{object_id}:{access.user_id}"
    )
    private_ids = [
        row.id for row in rows if private and row.ownership_scope_id == obj.ownership_scope_id
    ]
    public_ids = [row.id for row in rows if row.id not in private_ids]
    projected = {
        row.id: row
        for row in [
            *relationship_reads(session, private_ids, public=False),
            *relationship_reads(session, public_ids, public=True),
        ]
    }
    return Collection(
        items=[projected[row.id] for row in rows],
        next_cursor=cursor,
    )


@router.get("/search", response_model=Collection[ObjectView], operation_id="searchResearch")
def search(
    session: DbSession,
    access: Access,
    page: Pagination,
    q: Annotated[str, Query(min_length=1, max_length=500)],
    scope: Literal["public", "member"] = "public",
    workspace_id: UUID | None = None,
    kind: ObjectKind | None = None,
) -> Collection[ObjectView]:
    if scope == "public":
        candidate = aliased(SqlObjectRevision)
        selected_version_id = (
            select(candidate.id)
            .where(candidate.object_id == SqlResearchObject.id, public_condition(candidate.id))
            .order_by(candidate.number.desc())
            .limit(1)
            .correlate(SqlResearchObject)
            .scalar_subquery()
        )
    query = (
        select(SqlResearchObject)
        .join(
            SqlObjectRevision,
            SqlObjectRevision.id
            == (
                selected_version_id if scope == "public" else SqlResearchObject.current_revision_id
            ),
        )
        .where(
            or_(
                SqlObjectRevision.title.icontains(q, autoescape=True),
                SqlObjectRevision.content_md.icontains(q, autoescape=True),
            )
        )
    )
    if scope == "member":
        access.require_user_id()
        query = query.join(SqlProject, SqlProject.id == SqlResearchObject.project_id).where(
            access.member_condition(),
            SqlProject.archived_at.is_(None),
            SqlProject.deleted_at.is_(None),
        )
    else:
        query = query.where(public_condition(SqlObjectRevision.id))
    if workspace_id:
        query = query.where(SqlResearchObject.project_id == workspace_id)
    if kind:
        query = query.where(SqlResearchObject.canonical_kind == kind)
    rows, cursor = page.select(
        session,
        query,
        SqlResearchObject.id,
        scope=f"search:{scope}:{access.user_id}:{workspace_id}:{kind}:{q}",
    )
    return Collection(
        items=[object_read(session, row, public=scope != "member") for row in rows],
        next_cursor=cursor,
    )

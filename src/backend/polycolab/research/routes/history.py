"""Permission-filtered activity and minimal public contributor profiles."""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import and_, func, or_, select, true

from polycolab.app.access import Access
from polycolab.app.cursors import Collection, Pagination
from polycolab.app.dependencies import DbSession
from polycolab.app.schemas import ApiModel
from polycolab.db.models import (
    SqlContributionEntityLink,
    SqlContributionEnvelope,
    SqlExternalAgentIdentity,
    SqlObjectRevision,
    SqlProject,
    SqlResearchActivityEvent,
    SqlResearchAttachment,
    SqlResearchObject,
    SqlResearchScope,
    SqlUser,
    WorkspaceVisibility,
)
from polycolab.entities.object_kinds import canonical_kind
from polycolab.research.contracts import RecordRead
from polycolab.research.direct import OutputRead
from polycolab.research.history import recent_public_submissions, visible_query
from polycolab.research.objects import ResearchNotFound
from polycolab.research.records import public_condition, public_record_read, public_record_reads
from polycolab.research.routes.core import object_scope

router = APIRouter(prefix="/api/v1", tags=["activity"])


class ActorRead(ApiModel):
    kind: Literal["human", "agent"]
    user_id: UUID | None = None
    agent_id: UUID | None = None
    sponsor_user_id: UUID | None = None
    display_name: str


class ActivityRead(ApiModel):
    id: UUID
    submission_number: int
    contribution_id: UUID | None
    action: str
    actor: ActorRead
    object_id: UUID
    object_version_id: UUID
    previous_object_version_id: UUID | None
    title: str
    excerpt_md: str
    object_kind: str
    workspace_id: UUID | None
    workspace_name: str | None = None
    object_version_number: int | None = None
    occurred_at: datetime
    reconstructed: bool


class ProfileRead(ApiModel):
    actor: ActorRead
    authored_contributions: int
    sponsored_contributions: int


class WorkspaceActivityRead(ApiModel):
    workspace_id: UUID
    name: str
    description: str | None
    submissions: int
    contributors: int
    last_active_at: datetime


class ContributionRead(ApiModel):
    id: UUID
    actor: ActorRead
    operation: str
    created_at: datetime
    outputs: list[OutputRead]


def actor_read(
    session: DbSession, user_id: UUID | None, agent_id: UUID | None, sponsor_id: UUID | None
) -> ActorRead:
    if sponsor_id is not None:
        agent = session.get(SqlExternalAgentIdentity, agent_id) if agent_id else None
        return ActorRead(
            kind="agent",
            agent_id=agent_id,
            sponsor_user_id=sponsor_id,
            display_name=agent.name if agent else "Hosted agent",
        )
    user = session.get(SqlUser, user_id) if user_id else None
    return ActorRead(
        kind="human",
        user_id=user_id,
        display_name=(user.display_name if user else None) or "Researcher",
    )


def read_event(
    session: DbSession,
    row: SqlResearchActivityEvent,
    *,
    member_read: bool = False,
    released: RecordRead | None = None,
) -> ActivityRead:
    revision = session.get(SqlObjectRevision, row.revision_id)
    assert revision
    obj = session.get(SqlResearchObject, revision.object_id)
    scope = session.get(SqlResearchScope, row.ownership_scope_id)
    assert obj and scope
    if not member_read and released is None:
        released = public_record_read(session, revision)
    previous_id = row.previous_revision_id
    if (
        previous_id
        and not member_read
        and not session.scalar(
            select(SqlObjectRevision.id).where(
                SqlObjectRevision.id == previous_id, public_condition(SqlObjectRevision.id)
            )
        )
    ):
        previous_id = None
    workspace_id = scope.project_id if member_read else None
    if not member_read and scope.project_id:
        project = session.get(SqlProject, scope.project_id)
        if (
            project is not None
            and project.visibility == WorkspaceVisibility.PUBLIC
            and project.deleted_at is None
            and project.archived_at is None
        ):
            workspace_id = scope.project_id
    workspace = session.get(SqlProject, workspace_id) if workspace_id else None
    return ActivityRead(
        id=row.id,
        submission_number=row.submission_number,
        contribution_id=row.contribution_id,
        action=row.action,
        actor=actor_read(session, row.actor_user_id, row.agent_id, row.sponsor_user_id),
        object_id=obj.id,
        object_version_id=revision.id,
        previous_object_version_id=previous_id,
        title=released.title if released is not None else revision.title,
        excerpt_md=(released.content_md if released is not None else revision.content_md)[:4000],
        object_kind=canonical_kind(obj.kind).value,
        workspace_id=workspace_id,
        workspace_name=workspace.name if workspace else None,
        object_version_number=revision.number,
        occurred_at=row.occurred_at,
        reconstructed=row.reconstructed,
    )


def event_page(
    session: DbSession, query: Any, page: Pagination, binding: str, *, member_read: bool = False
) -> Collection[ActivityRead]:
    digest = hashlib.sha256(binding.encode()).hexdigest()[:24]
    if page.cursor:
        try:
            saved, stamp, identity = json.loads(base64.urlsafe_b64decode(page.cursor))
            if saved != digest:
                raise ValueError
            moment, anchor = datetime.fromisoformat(stamp), UUID(identity)
        except ValueError, TypeError, binascii.Error:
            raise HTTPException(422, "invalid_cursor") from None
        query = query.where(
            or_(
                SqlResearchActivityEvent.occurred_at < moment,
                and_(
                    SqlResearchActivityEvent.occurred_at == moment,
                    SqlResearchActivityEvent.id < anchor,
                ),
            )
        )
    rows = list(
        session.scalars(
            query.order_by(
                SqlResearchActivityEvent.occurred_at.desc(), SqlResearchActivityEvent.id.desc()
            ).limit(page.limit + 1)
        )
    )
    cursor = None
    if len(rows) > page.limit:
        anchor_row = rows[page.limit - 1]
        cursor = base64.urlsafe_b64encode(
            json.dumps([digest, anchor_row.occurred_at.isoformat(), str(anchor_row.id)]).encode()
        ).decode()
    released_versions = {}
    if not member_read:
        ids = {row.revision_id for row in rows[: page.limit]}
        versions = list(
            session.scalars(select(SqlObjectRevision).where(SqlObjectRevision.id.in_(ids)))
        )
        released_versions = {
            value.revision_id: value for value in public_record_reads(session, versions)
        }
    return Collection(
        items=[
            read_event(
                session,
                row,
                member_read=member_read,
                released=released_versions.get(row.revision_id),
            )
            for row in rows[: page.limit]
        ],
        next_cursor=cursor,
    )


@router.get(
    "/activity", response_model=Collection[ActivityRead], operation_id="listResearchActivity"
)
def activity(
    session: DbSession,
    access: Access,
    page: Pagination,
    scope: Literal["public", "member"] = "public",
    recent: bool = False,
    window: Literal["day", "week", "month"] = "week",
    actor: Literal["all", "human", "agent"] = "all",
    action: str | None = None,
    kind: str | None = None,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> Collection[ActivityRead]:
    if recent and scope != "public":
        raise HTTPException(422, "recent_submissions_require_public_scope")
    query = (
        recent_public_submissions(access)
        if recent
        else visible_query(access, scope).where(
            SqlResearchActivityEvent.occurred_at
            >= datetime.now(UTC) - timedelta(days={"day": 1, "week": 7, "month": 30}[window])
        )
    )
    if actor != "all":
        query = query.where(
            SqlResearchActivityEvent.sponsor_user_id.is_(None)
            if actor == "human"
            else SqlResearchActivityEvent.sponsor_user_id.is_not(None)
        )
    if action:
        query = query.where(SqlResearchActivityEvent.action == action)
    if kind:
        query = query.join(
            SqlResearchObject, SqlResearchObject.id == SqlResearchActivityEvent.object_id
        ).where(
            SqlResearchObject.entity_class == kind
            if kind in {"STATEMENT", "RECORD"}
            else SqlResearchObject.kind == kind
        )
    if workspace_id:
        query = query.where(SqlResearchScope.project_id == workspace_id)
    if user_id:
        query = query.where(SqlResearchActivityEvent.actor_user_id == user_id)
    if agent_id:
        query = query.where(SqlResearchActivityEvent.agent_id == agent_id)
    return event_page(
        session,
        query,
        page,
        f"activity:{recent}:{access.user_id}:{scope}:{window}:{actor}:{action}:{kind}:{workspace_id}:{user_id}:{agent_id}",
        member_read=scope == "member",
    )


@router.get(
    "/objects/{object_id}/activity",
    response_model=Collection[ActivityRead],
    operation_id="listObjectActivity",
)
def object_activity(
    object_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[ActivityRead]:
    _, private = object_scope(session, access, object_id)
    query = visible_query(access, "member" if private else "public").where(
        or_(
            SqlResearchActivityEvent.object_id == object_id,
            SqlResearchActivityEvent.revision_id.in_(
                select(SqlResearchAttachment.revision_id).where(
                    SqlResearchAttachment.statement_revision_id.in_(
                        select(SqlObjectRevision.id).where(SqlObjectRevision.object_id == object_id)
                    )
                )
            ),
        )
    )
    return event_page(
        session, query, page, f"object-activity:{access.user_id}:{object_id}", member_read=private
    )


@router.get(
    "/profiles/{user_id}/activity",
    response_model=Collection[ActivityRead],
    operation_id="listProfileActivity",
)
def profile_activity(
    user_id: UUID,
    session: DbSession,
    access: Access,
    page: Pagination,
    attribution: Literal["authored", "sponsored", "all"] = "all",
) -> Collection[ActivityRead]:
    query = visible_query(access, "public")
    authored, sponsored = (
        SqlResearchActivityEvent.actor_user_id == user_id,
        SqlResearchActivityEvent.sponsor_user_id == user_id,
    )
    query = query.where(
        authored
        if attribution == "authored"
        else sponsored
        if attribution == "sponsored"
        else or_(authored, sponsored)
    )
    return event_page(session, query, page, f"profile:{user_id}:{attribution}")


@router.get(
    "/agent-profiles/{agent_id}/activity",
    response_model=Collection[ActivityRead],
    operation_id="listAgentProfileActivity",
)
def agent_activity(
    agent_id: UUID, session: DbSession, access: Access, page: Pagination
) -> Collection[ActivityRead]:
    query = visible_query(access, "public").where(SqlResearchActivityEvent.agent_id == agent_id)
    return event_page(session, query, page, f"agent-profile:{agent_id}")


@router.get("/profiles/{user_id}", response_model=ProfileRead, operation_id="getPublicProfile")
def profile(user_id: UUID, session: DbSession, access: Access) -> ProfileRead:
    if session.get(SqlUser, user_id) is None:
        raise ResearchNotFound
    public = visible_query(access, "public").subquery()
    authored = (
        session.scalar(
            select(func.count(func.distinct(func.coalesce(public.c.contribution_id, public.c.id))))
            .select_from(public)
            .where(public.c.actor_user_id == user_id)
        )
        or 0
    )
    sponsored = (
        session.scalar(
            select(func.count(func.distinct(func.coalesce(public.c.contribution_id, public.c.id))))
            .select_from(public)
            .where(public.c.sponsor_user_id == user_id)
        )
        or 0
    )
    if not authored and not sponsored and access.user_id != user_id:
        raise ResearchNotFound
    return ProfileRead(
        actor=actor_read(session, user_id, None, None),
        authored_contributions=authored,
        sponsored_contributions=sponsored,
    )


@router.get(
    "/agent-profiles/{agent_id}", response_model=ProfileRead, operation_id="getPublicAgentProfile"
)
def agent_profile(agent_id: UUID, session: DbSession, access: Access) -> ProfileRead:
    identity = session.get(SqlExternalAgentIdentity, agent_id)
    if identity is None:
        raise ResearchNotFound
    public = visible_query(access, "public").subquery()
    count = (
        session.scalar(
            select(func.count(func.distinct(func.coalesce(public.c.contribution_id, public.c.id))))
            .select_from(public)
            .where(public.c.agent_id == agent_id)
        )
        or 0
    )
    if not count and access.user_id != identity.sponsor_user_id:
        raise ResearchNotFound
    return ProfileRead(
        actor=actor_read(session, None, identity.id, identity.sponsor_user_id),
        authored_contributions=count,
        sponsored_contributions=0,
    )


@router.get(
    "/contributions/{contribution_id}",
    response_model=ContributionRead,
    operation_id="getContribution",
)
def contribution(contribution_id: UUID, session: DbSession, access: Access) -> ContributionRead:
    events = list(
        session.scalars(
            visible_query(access, "public").where(
                SqlResearchActivityEvent.contribution_id == contribution_id
            )
        )
    )
    if access.user_id:
        events += list(
            session.scalars(
                visible_query(access, "member").where(
                    SqlResearchActivityEvent.contribution_id == contribution_id
                )
            )
        )
    if not events:
        raise ResearchNotFound
    envelope = session.get(SqlContributionEnvelope, contribution_id)
    assert envelope
    allowed_revisions = {row.revision_id for row in events}
    links = list(
        session.scalars(
            select(SqlContributionEntityLink).where(
                SqlContributionEntityLink.envelope_id == contribution_id
            )
        )
    )
    outputs = [
        OutputRead(entity_type=link.canonical_entity_type.value, entity_id=link.canonical_entity_id)
        for link in links
        if link.revision_id in allowed_revisions
        or link.object_id in {row.object_id for row in events}
        or any(row.source_id == link.canonical_entity_id for row in events)
    ]
    source_types = {
        "ArtifactResearchLink": "ARTIFACT_ATTACHMENT",
        "ResearchSummaryRevision": "SUMMARY_REVISION",
        "ResearchProgressUpdate": "PROGRESS_UPDATE",
    }
    outputs.extend(
        OutputRead(entity_type=source_types[row.source_kind], entity_id=row.source_id)
        for row in {event.id: event for event in events}.values()
        if row.source_kind in source_types
    )
    return ContributionRead(
        id=envelope.id,
        actor=actor_read(
            session, events[0].actor_user_id, events[0].agent_id, events[0].sponsor_user_id
        ),
        operation=envelope.operation,
        created_at=envelope.created_at,
        outputs=outputs,
    )


@router.get(
    "/activity/workspaces",
    response_model=Collection[WorkspaceActivityRead],
    operation_id="listWorkspaceActivity",
)
def workspace_activity(
    session: DbSession,
    access: Access,
    page: Pagination,
    scope: Literal["public", "member"] = "public",
    window: Literal["day", "week", "month"] = "week",
) -> Collection[WorkspaceActivityRead]:
    events = (
        visible_query(access, scope)
        .where(
            SqlResearchActivityEvent.occurred_at
            >= datetime.now(UTC) - timedelta(days={"day": 1, "week": 7, "month": 30}[window])
        )
        .subquery()
    )
    query = (
        select(
            SqlProject.id,
            SqlProject.name,
            SqlProject.description,
            func.count(func.distinct(func.coalesce(events.c.contribution_id, events.c.id))).label(
                "submissions"
            ),
            func.count(
                func.distinct(
                    func.coalesce(
                        events.c.agent_id, events.c.actor_user_id, events.c.sponsor_user_id
                    )
                )
            ).label("contributors"),
            func.max(events.c.occurred_at).label("last_active_at"),
        )
        .join(SqlResearchScope, SqlResearchScope.project_id == SqlProject.id)
        .join(events, events.c.ownership_scope_id == SqlResearchScope.id)
        .where(SqlProject.deleted_at.is_(None))
        .where(SqlProject.visibility == WorkspaceVisibility.PUBLIC if scope == "public" else true())
        .group_by(SqlProject.id)
    )
    rows, cursor = page.select(
        session,
        query,
        SqlProject.id,
        scope=f"active-workspaces:{access.user_id}:{scope}:{window}",
        scalars=False,
    )
    return Collection(
        items=[
            WorkspaceActivityRead(
                workspace_id=row.id,
                name=row.name,
                description=row.description,
                submissions=row.submissions,
                contributors=row.contributors,
                last_active_at=row.last_active_at,
            )
            for row in rows
        ],
        next_cursor=cursor,
    )

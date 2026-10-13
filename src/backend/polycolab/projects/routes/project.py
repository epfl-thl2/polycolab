"""User, project, research, and gateway-profile project endpoints."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, human_actor
from polycolab.access.authorization import (
    ProjectAction,
    ProjectNotFound,
    project_policy,
    require_manage_credentials,
    require_manage_members,
    require_project_management,
    require_project_write,
)
from polycolab.accounts.schemas import UserRead
from polycolab.agents.schemas import AgentContributionRead, ContributionEntityType
from polycolab.agents.sessions import archive_project_agent_sessions
from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession, Page, paginated
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import ArtifactAttachmentPage
from polycolab.db.converters.projects import invitation as invitation_entity
from polycolab.db.models import (
    SqlContributionEntityLink,
    SqlContributionEnvelope,
    SqlInvitation,
    SqlLocalAccount,
    SqlMembership,
    SqlObjectRevision,
    SqlProject,
    SqlRecordModeration,
    SqlRelationAssertion,
    SqlResearchComment,
    SqlResearchObject,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.enums import ContributionActorKind, ProjectVisibility
from polycolab.entities.projects import Membership as MembershipEntity
from polycolab.entities.projects import Project as ProjectEntity
from polycolab.entities.time import utc_now
from polycolab.model_gateway.schemas import (
    GatewayProfileCreate,
    GatewayProfileRead,
    GatewayProfileRotate,
)
from polycolab.model_gateway.service import (
    GatewayNotFound,
    ProviderFailure,
    UnsafeBaseUrl,
    create_profile,
    delete_profile,
    profile_for_user,
    rotate_profile,
    validate_profile_credential,
)
from polycolab.projects.schemas import (
    InvitationAccept,
    InvitationAccepted,
    InvitationCreate,
    InvitationRead,
    MembershipCreate,
    MembershipRead,
    MembershipUpdate,
    ProjectCreate,
    ProjectMemberRead,
    ProjectUpdate,
    PublicProjectRead,
)
from polycolab.projects.service import (
    accept_invitation,
    add_membership,
    change_membership_role,
    create_invitation,
    create_project,
    member_counts,
    remove_membership,
    resolve_membership_username,
    revoke_invitation,
)
from polycolab.research.contracts import RecordModerationRead, RecordModerationWrite, RecordRead
from polycolab.research.objects import (
    ResearchNotFound,
    comments_for_object,
    create_comment,
    create_object,
    create_relation,
    create_revision,
    dependents,
    neighborhood,
    object_by_id,
    object_in_project,
    relations_for_object,
    revision_in_project,
    revisions_for_object,
)
from polycolab.research.schemas import (
    AuthorRead,
    CommentCreate,
    CommentRead,
    PublicAgentProvenanceRead,
    PublicAuthorRead,
    PublicCommentRead,
    PublicRelationRead,
    PublicResearchObjectRead,
    PublicRevisionRead,
    RelationCreate,
    RelationRead,
    ResearchObjectCreate,
    ResearchObjectRead,
    RevisionCreate,
    RevisionRead,
)
from polycolab.research.version_projections import relationship_reads
from polycolab.research.version_schemas import (
    ObjectVersionRelationshipRead,
    VersionNeighborhoodNodeRead,
    VersionNeighborhoodRead,
)

router = APIRouter(prefix="/api/v1")
ModerationRetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def _user_for_actor(session: Session, actor: Actor) -> SqlUser:
    if actor.human_user_id is None:
        raise ProjectNotFound
    user = session.get(SqlUser, actor.human_user_id)
    if user is None:
        raise ProjectNotFound
    return user


def _member_read(
    project: SqlProject | ProjectEntity,
    membership: SqlMembership | MembershipEntity,
    member_count: int,
) -> ProjectMemberRead:
    return ProjectMemberRead(
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


def _public_object(session: Session, project_id: UUID, object_id: UUID) -> SqlResearchObject:
    _public_project(session, project_id)
    research_object = session.scalar(
        select(SqlResearchObject).where(
            SqlResearchObject.id == object_id,
            SqlResearchObject.project_id == project_id,
            ~exists(
                select(SqlRecordModeration.object_id).where(
                    SqlRecordModeration.object_id == SqlResearchObject.id,
                    SqlRecordModeration.hidden.is_(True),
                )
            ),
        )
    )
    if research_object is None:
        raise ProjectNotFound
    return research_object


def _membership_read(
    session: Session, membership: SqlMembership | MembershipEntity
) -> MembershipRead:
    member = session.get(SqlUser, membership.user_id)
    if member is None:
        raise ProjectNotFound
    account = None
    if member.issuer == "polycolab-local":
        try:
            account = session.get(SqlLocalAccount, UUID(member.subject))
        except ValueError:
            account = None
    return MembershipRead(
        user_id=membership.user_id,
        username=account.username if account is not None else None,
        display_name=(
            account.display_name or account.username if account is not None else member.display_name
        ),
        role=membership.role,
        created_at=membership.created_at,
    )


def _author_read(session: Session, user_id: UUID) -> AuthorRead:
    user = session.get(SqlUser, user_id)
    # Foreign keys make this unreachable in production, but never serialize an
    # absent author as a made-up identity if legacy data is incomplete.
    if user is None:
        raise ProjectNotFound
    return AuthorRead(id=user.id, display_name=user.display_name)


def _revision_read(
    session: Session, revision: SqlObjectRevision, *, record: RecordRead | None = None
) -> RevisionRead:
    from polycolab.research.records import record_read
    from polycolab.research.schemas import VersionContentRead

    record = record or record_read(session, revision, revision.project_id)
    return RevisionRead(
        **record.model_dump(include=set(VersionContentRead.model_fields)),
        id=revision.id,
        object_id=revision.object_id,
        number=revision.number,
        title=revision.title,
        content_md=revision.content_md,
        base_revision_id=revision.base_revision_id,
        author=AuthorRead(id=revision.created_by_user_id, display_name=record.author_display_name),
        provenance_kind=revision.provenance_kind,
        created_at=revision.created_at,
    )


def _object_read(session: Session, research_object: SqlResearchObject) -> ResearchObjectRead:
    if research_object.current_revision_id is None:
        raise ProjectNotFound
    revision = revision_in_project(
        session,
        project_id=research_object.project_id,
        revision_id=research_object.current_revision_id,
        object_id=research_object.id,
    )
    return ResearchObjectRead(
        id=research_object.id,
        project_id=research_object.project_id,
        kind=research_object.kind,
        current_revision_id=revision.id,
        author=_author_read(session, research_object.created_by_user_id),
        provenance_kind=research_object.provenance_kind,
        created_at=research_object.created_at,
        updated_at=research_object.updated_at,
        current_revision=_revision_read(session, revision),
    )


def _relation_read(session: Session, relation: SqlRelationAssertion) -> RelationRead:
    return RelationRead(
        id=relation.id,
        project_id=relation.project_id,
        source_revision_id=relation.source_revision_id,
        target_revision_id=relation.target_revision_id,
        relation_type=relation.relation_type,
        rationale=relation.rationale,
        author=_author_read(session, relation.created_by_user_id),
        provenance_kind=relation.provenance_kind,
        created_at=relation.created_at,
    )


def _comment_read(session: Session, comment: SqlResearchComment) -> CommentRead:
    return CommentRead(
        id=comment.id,
        object_id=comment.object_id,
        revision_id=comment.revision_id,
        body_md=comment.body_md,
        author=_author_read(session, comment.created_by_user_id),
        provenance_kind=comment.provenance_kind,
        created_at=comment.created_at,
    )


def _public_author_read(session: Session, user_id: UUID) -> PublicAuthorRead:
    user = session.get(SqlUser, user_id)
    if user is None:
        raise ProjectNotFound
    return PublicAuthorRead(display_name=user.display_name)


def _public_provenance(session: Session, contribution_id: UUID) -> PublicAgentProvenanceRead | None:
    envelope = session.get(SqlContributionEnvelope, contribution_id)
    if envelope is None:
        raise ProjectNotFound
    if envelope.actor_kind is ContributionActorKind.AGENT:
        return PublicAgentProvenanceRead(agent_generated=True)
    return None


def _public_revision_read(
    session: Session, revision: SqlObjectRevision, *, record: RecordRead | None = None
) -> PublicRevisionRead:
    from polycolab.research.records import public_record_read
    from polycolab.research.schemas import VersionContentRead

    record = record or public_record_read(session, revision)
    return PublicRevisionRead(
        **record.model_dump(include=set(VersionContentRead.model_fields)),
        id=revision.id,
        number=record.number,
        title=record.title,
        content_md=record.content_md,
        base_revision_id=record.base_revision_id,
        author=PublicAuthorRead(display_name=record.author_display_name),
        provenance=PublicAgentProvenanceRead() if record.actor_kind == "AGENT" else None,
        created_at=revision.created_at,
    )


def _public_object_read(
    session: Session, research_object: SqlResearchObject
) -> PublicResearchObjectRead:
    from polycolab.research.records import public_condition

    revision = session.scalar(
        select(SqlObjectRevision)
        .where(
            SqlObjectRevision.object_id == research_object.id,
            public_condition(SqlObjectRevision.id),
        )
        .order_by(SqlObjectRevision.number.desc())
        .limit(1)
    )
    if revision is None:
        raise ProjectNotFound
    return PublicResearchObjectRead(
        id=research_object.id,
        kind=research_object.kind,
        current_revision_id=revision.id,
        created_at=research_object.created_at,
        provenance=_public_provenance(session, research_object.contribution_id),
        current_revision=_public_revision_read(session, revision),
    )


def _public_relation_read(session: Session, relation: SqlRelationAssertion) -> PublicRelationRead:
    return PublicRelationRead(
        id=relation.id,
        source_revision_id=relation.source_revision_id,
        target_revision_id=relation.target_revision_id,
        relation_type=relation.relation_type,
        rationale=relation.rationale,
        author=_public_author_read(session, relation.created_by_user_id),
        provenance=_public_provenance(session, relation.contribution_id),
        created_at=relation.created_at,
    )


def _public_comment_read(session: Session, comment: SqlResearchComment) -> PublicCommentRead:
    return PublicCommentRead(
        id=comment.id,
        revision_id=comment.revision_id,
        body_md=comment.body_md,
        author=_public_author_read(session, comment.created_by_user_id),
        provenance=_public_provenance(session, comment.contribution_id),
        created_at=comment.created_at,
    )


def _neighborhood_nodes(
    session: Session,
    *,
    project_id: UUID,
    selected_revision_id: UUID,
    relations: list[SqlRelationAssertion],
) -> list[SqlObjectRevision]:
    revision_ids = {selected_revision_id}
    for relation in relations:
        revision_ids.update((relation.source_revision_id, relation.target_revision_id))
    return list(
        session.scalars(
            select(SqlObjectRevision)
            .where(
                SqlObjectRevision.project_id == project_id, SqlObjectRevision.id.in_(revision_ids)
            )
            .order_by(SqlObjectRevision.number, SqlObjectRevision.id)
        )
    )


def _object_scope(
    session: Session, *, object_id: UUID, user: IdentifiedUser, action: ProjectAction
) -> SqlResearchObject:
    research_object = object_by_id(session, object_id=object_id)
    project_policy.require_scope(
        SqlAlchemyTransaction(session), research_object.project_id, user.id, action
    )
    return research_object


@router.get("/users/me", response_model=UserRead, operation_id="getCurrentUser", tags=["users"])
def get_current_user(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


def _gateway_profile_read(profile) -> GatewayProfileRead:  # type: ignore[no-untyped-def]
    return GatewayProfileRead.model_validate(profile)


@router.post(
    "/gateway/profiles",
    response_model=GatewayProfileRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createGatewayProfile",
    tags=["gateway-profiles"],
)
def post_gateway_profile(
    payload: GatewayProfileCreate, request: Request, session: DbSession, user: CurrentUser
) -> GatewayProfileRead:
    require_manage_credentials(human_actor(user.id))
    wrapper = request.app.state.credential_wrapper
    try:
        profile = create_profile(
            session,
            user=user,
            wrapper=wrapper,
            display_name=payload.display_name,
            base_url=payload.base_url,
            model_id=payload.model_id,
            api_key=payload.api_key.get_secret_value(),
            wire_api=payload.wire_api,
            production=request.app.state.settings.app_env.value != "local",
        )
    except UnsafeBaseUrl:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    return _gateway_profile_read(profile)


@router.get(
    "/gateway/profiles",
    response_model=list[GatewayProfileRead],
    operation_id="listGatewayProfiles",
    tags=["gateway-profiles"],
)
def list_gateway_profiles(
    response: Response, page: Page, session: DbSession, user: CurrentUser
) -> list[GatewayProfileRead]:
    from polycolab.db.models import SqlGatewayProfile

    profiles = [
        _gateway_profile_read(profile)
        for profile in session.scalars(
            select(SqlGatewayProfile)
            .where(SqlGatewayProfile.user_id == user.id, SqlGatewayProfile.deleted_at.is_(None))
            .order_by(SqlGatewayProfile.created_at.desc(), SqlGatewayProfile.id.desc())
        )
    ]
    return paginated(profiles, page, response)


@router.post(
    "/gateway/profiles/{profile_id}/rotate",
    response_model=GatewayProfileRead,
    operation_id="rotateGatewayProfile",
    tags=["gateway-profiles"],
)
def post_gateway_profile_rotate(
    profile_id: UUID,
    payload: GatewayProfileRotate,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> GatewayProfileRead:
    require_manage_credentials(human_actor(user.id))
    try:
        return _gateway_profile_read(
            rotate_profile(
                session,
                profile_id=profile_id,
                user=user,
                wrapper=request.app.state.credential_wrapper,
                api_key=payload.api_key.get_secret_value(),
            )
        )
    except GatewayNotFound:
        raise ProjectNotFound from None


@router.post(
    "/gateway/profiles/{profile_id}/validate",
    response_model=GatewayProfileRead,
    operation_id="validateGatewayProfile",
    tags=["gateway-profiles"],
)
def post_gateway_profile_validate(
    profile_id: UUID, request: Request, session: DbSession, user: CurrentUser
) -> GatewayProfileRead:
    require_manage_credentials(human_actor(user.id))
    try:
        profile = profile_for_user(session, profile_id=profile_id, user_id=user.id)
        validate_profile_credential(
            profile=profile,
            user_id=user.id,
            wrapper=request.app.state.credential_wrapper,
            transport=request.app.state.provider_transport,
        )
    except GatewayNotFound:
        raise ProjectNotFound from None
    except UnsafeBaseUrl, ProviderFailure:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    return _gateway_profile_read(profile)


@router.delete(
    "/gateway/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteGatewayProfile",
    tags=["gateway-profiles"],
)
def remove_gateway_profile(profile_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    require_manage_credentials(human_actor(user.id))
    try:
        delete_profile(session, profile_id=profile_id, user=user)
    except GatewayNotFound:
        raise ProjectNotFound from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def list_public_projects(
    request: Request,
    session: DbSession,
    page: Page,
    response: Response,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> list[PublicProjectRead]:
    query = select(SqlProject).where(
        SqlProject.visibility == ProjectVisibility.PUBLIC,
        SqlProject.archived_at.is_(None),
        SqlProject.deleted_at.is_(None),
    )
    if q is not None:
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(SqlProject.name.ilike(pattern), SqlProject.description.ilike(pattern))
        )
    projects = list(
        session.scalars(query.order_by(SqlProject.updated_at.desc(), SqlProject.id.desc()))
    )
    return paginated([_public_project_read(project) for project in projects], page, response)


def get_public_project(project_id: UUID, request: Request, session: DbSession) -> PublicProjectRead:
    return _public_project_read(_public_project(session, project_id))


def list_public_research_objects(
    project_id: UUID,
    request: Request,
    session: DbSession,
    page: Page,
    response: Response,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> list[PublicResearchObjectRead]:
    _public_project(session, project_id)
    query = select(SqlResearchObject).where(
        SqlResearchObject.project_id == project_id,
        ~exists(
            select(SqlRecordModeration.object_id).where(
                SqlRecordModeration.object_id == SqlResearchObject.id,
                SqlRecordModeration.hidden.is_(True),
            )
        ),
    )
    if q is not None:
        pattern = f"%{q.strip()}%"
        query = query.join(
            SqlObjectRevision, SqlObjectRevision.id == SqlResearchObject.current_revision_id
        ).where(
            or_(SqlObjectRevision.title.ilike(pattern), SqlObjectRevision.content_md.ilike(pattern))
        )
    objects = list(
        session.scalars(query.order_by(SqlResearchObject.updated_at.desc(), SqlResearchObject.id))
    )
    return paginated([_public_object_read(session, item) for item in objects], page, response)


def get_public_research_object(
    project_id: UUID, object_id: UUID, request: Request, session: DbSession
) -> PublicResearchObjectRead:
    return _public_object_read(session, _public_object(session, project_id, object_id))


def list_public_object_revisions(
    project_id: UUID,
    object_id: UUID,
    request: Request,
    session: DbSession,
    page: Page,
    response: Response,
) -> list[PublicRevisionRead]:
    research_object = _public_object(session, project_id, object_id)
    return paginated(
        [
            _public_revision_read(session, item)
            for item in revisions_for_object(session, object_id=research_object.id)
        ],
        page,
        response,
    )


def list_public_object_relations(
    project_id: UUID,
    object_id: UUID,
    request: Request,
    session: DbSession,
    page: Page,
    response: Response,
) -> list[PublicRelationRead]:
    research_object = _public_object(session, project_id, object_id)
    from polycolab.research.records import public_revision

    visible: list[SqlRelationAssertion] = []
    for relation in relations_for_object(session, object_id=research_object.id):
        try:
            public_revision(session, relation.source_revision_id)
            public_revision(session, relation.target_revision_id)
        except ResearchNotFound:
            continue
        visible.append(relation)
    return paginated(
        [_public_relation_read(session, item) for item in visible],
        page,
        response,
    )


def list_public_object_comments(
    project_id: UUID,
    object_id: UUID,
    request: Request,
    session: DbSession,
    page: Page,
    response: Response,
) -> list[PublicCommentRead]:
    research_object = _public_object(session, project_id, object_id)
    return paginated(
        [
            _public_comment_read(session, item)
            for item in comments_for_object(session, object_id=research_object.id)
        ],
        page,
        response,
    )


@router.post(
    "/operator/projects/{project_id}/objects/{object_id}/moderation",
    response_model=RecordModerationRead,
    operation_id="moderatePublicProjectRecord",
    tags=["public-research-moderation"],
)
def moderate_public_project_record(
    project_id: UUID,
    object_id: UUID,
    payload: RecordModerationWrite,
    key: ModerationRetryKey,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
) -> RecordModerationRead:
    from polycolab.catalogue.moderation import moderate_public_project_record as moderate

    return moderate(
        session,
        actor=actor,
        settings=request.app.state.settings,
        project_id=project_id,
        object_id=object_id,
        payload=payload,
        key=key,
    )


@router.get(
    "/operator/projects/{project_id}/objects/{object_id}/moderation",
    response_model=list[RecordModerationRead],
    operation_id="listPublicProjectRecordModerationAudit",
    tags=["public-research-moderation"],
)
def list_public_project_record_moderation_audit(
    project_id: UUID,
    object_id: UUID,
    request: Request,
    session: DbSession,
    actor: CurrentActor,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[UUID | None, Query()] = None,
) -> list[RecordModerationRead]:
    from polycolab.catalogue.moderation import public_project_moderation_history

    return public_project_moderation_history(
        session,
        actor=actor,
        settings=request.app.state.settings,
        project_id=project_id,
        object_id=object_id,
        limit=limit,
        after=cursor,
    )


def list_public_project_artifacts(
    project_id: UUID,
    request: Request,
    session: DbSession,
    revision_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ArtifactAttachmentPage:
    return artifacts.list_public_attachments(
        session,
        project_id=project_id,
        revision_id=revision_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/projects",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProject",
    tags=["projects"],
)
def post_project(
    payload: ProjectCreate, request: Request, session: DbSession, actor: CurrentActor
) -> ProjectMemberRead:
    require_project_management(actor)
    user = _user_for_actor(session, actor)
    visibility = payload.visibility
    project = create_project(
        SqlAlchemyTransaction(session),
        creator=user,
        name=payload.name,
        description=payload.description,
        visibility=visibility,
    )
    membership = project_policy.membership(SqlAlchemyTransaction(session), project.id, user.id)
    assert membership is not None
    return _member_read(
        project, membership, member_counts(SqlAlchemyTransaction(session), [project.id])[project.id]
    )


def list_projects(
    session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[ProjectMemberRead]:
    projects = session.execute(
        select(SqlProject, SqlMembership)
        .join(SqlMembership, SqlMembership.project_id == SqlProject.id)
        .where(SqlMembership.user_id == user.id, SqlProject.deleted_at.is_(None))
        .order_by(SqlProject.created_at.desc(), SqlProject.id.desc())
    ).all()
    counts = member_counts(SqlAlchemyTransaction(session), [project.id for project, _ in projects])
    return paginated(
        [_member_read(project, membership, counts[project.id]) for project, membership in projects],
        page,
        response,
    )


def get_project(project_id: UUID, session: DbSession, user: CurrentUser) -> ProjectMemberRead:
    scope = project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.VIEW
    )
    return _member_read(
        scope.project,
        scope.membership,
        member_counts(SqlAlchemyTransaction(session), [project_id])[project_id],
    )


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectMemberRead,
    operation_id="updateProject",
    tags=["projects"],
)
def patch_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> ProjectMemberRead:
    require_project_management(human_actor(user.id))
    scope = project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_SETTINGS
    )
    project = scope.project
    values = payload.model_dump(exclude_unset=True)
    archived = values.pop("archived", None)
    project = replace(project, **values)
    if archived is not None:
        project = replace(project, archived_at=utc_now() if archived else None)
    transaction = SqlAlchemyTransaction(session)
    project = transaction.projects.update_settings(
        project.id,
        name=project.name,
        description=project.description,
        visibility=project.visibility,
        archived_at=project.archived_at,
    )
    if archived:
        archive_project_agent_sessions(session, project_id=project.id)
    transaction.commit()
    return _member_read(
        project, scope.membership, member_counts(transaction, [project.id])[project.id]
    )


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteProject",
    tags=["projects"],
)
def delete_project(project_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    require_project_management(human_actor(user.id))
    project = project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.DELETE
    ).project
    SqlAlchemyTransaction(session).projects.mark_deleted(project.id, at=utc_now())
    archive_project_agent_sessions(session, project_id=project.id)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/projects/{project_id}/members",
    response_model=list[MembershipRead],
    operation_id="listProjectMembers",
    tags=["memberships"],
)
def list_members(
    project_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[MembershipRead]:
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    memberships = session.scalars(
        select(SqlMembership)
        .where(SqlMembership.project_id == project_id)
        .order_by(SqlMembership.created_at, SqlMembership.id)
    )
    return paginated(
        [_membership_read(session, membership) for membership in memberships], page, response
    )


@router.post(
    "/projects/{project_id}/members",
    response_model=MembershipRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="addProjectMember",
    tags=["memberships"],
)
def post_member(
    project_id: UUID, payload: MembershipCreate, session: DbSession, user: CurrentUser
) -> MembershipRead:
    require_manage_members(human_actor(user.id))
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    member_user_id = payload.user_id
    if payload.username is not None:
        member_user_id = resolve_membership_username(
            SqlAlchemyTransaction(session), username=payload.username
        ).id
    assert member_user_id is not None
    return _membership_read(
        session,
        add_membership(
            SqlAlchemyTransaction(session),
            project_id=project_id,
            user_id=member_user_id,
            role=payload.role,
            invited_by=user.id,
        ),
    )


@router.patch(
    "/projects/{project_id}/members/{member_user_id}",
    response_model=MembershipRead,
    operation_id="updateProjectMember",
    tags=["memberships"],
)
def patch_member(
    project_id: UUID,
    member_user_id: UUID,
    payload: MembershipUpdate,
    session: DbSession,
    user: CurrentUser,
) -> MembershipRead:
    require_manage_members(human_actor(user.id))
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    return _membership_read(
        session,
        change_membership_role(
            SqlAlchemyTransaction(session),
            project_id=project_id,
            user_id=member_user_id,
            role=payload.role,
        ),
    )


@router.delete(
    "/projects/{project_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="removeProjectMember",
    tags=["memberships"],
)
def delete_member(
    project_id: UUID, member_user_id: UUID, session: DbSession, user: CurrentUser
) -> Response:
    require_manage_members(human_actor(user.id))
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    remove_membership(SqlAlchemyTransaction(session), project_id=project_id, user_id=member_user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/invitations",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProjectInvitation",
    tags=["invitations"],
)
def post_invitation(
    project_id: UUID,
    payload: InvitationCreate,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> InvitationRead:
    require_manage_members(human_actor(user.id))
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    invitation = create_invitation(
        SqlAlchemyTransaction(session),
        project_id=project_id,
        email=payload.email,
        role=payload.role,
        invited_by=user.id,
        delivery=request.app.state.invitation_delivery,
    )
    return InvitationRead.model_validate(invitation)


@router.get(
    "/projects/{project_id}/invitations",
    response_model=list[InvitationRead],
    operation_id="listProjectInvitations",
    tags=["invitations"],
)
def list_invitations(
    project_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[InvitationRead]:
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    invitations = session.scalars(
        select(SqlInvitation)
        .where(SqlInvitation.project_id == project_id)
        .order_by(SqlInvitation.created_at, SqlInvitation.id)
    )
    return paginated(
        [InvitationRead.model_validate(invitation) for invitation in invitations], page, response
    )


@router.delete(
    "/projects/{project_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeProjectInvitation",
    tags=["invitations"],
)
def delete_invitation(
    project_id: UUID, invitation_id: UUID, session: DbSession, user: CurrentUser
) -> Response:
    require_manage_members(human_actor(user.id))
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.MANAGE_MEMBERS
    )
    invitation = session.scalar(
        select(SqlInvitation).where(
            SqlInvitation.id == invitation_id, SqlInvitation.project_id == project_id
        )
    )
    if invitation is None:
        raise ProjectNotFound
    revoke_invitation(SqlAlchemyTransaction(session), invitation_entity(invitation))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invitations/accept",
    response_model=InvitationAccepted,
    operation_id="acceptInvitation",
    tags=["invitations"],
)
def post_accept_invitation(
    payload: InvitationAccept, session: DbSession, user: CurrentUser
) -> InvitationAccepted:
    project_id, role = accept_invitation(
        SqlAlchemyTransaction(session), token=payload.token.get_secret_value(), user=user
    )
    return InvitationAccepted(project_id=project_id, role=role)


def post_research_object(
    project_id: UUID, payload: ResearchObjectCreate, session: DbSession, user: CurrentUser
) -> ResearchObjectRead:
    require_project_write(human_actor(user.id), project_id=project_id)
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.CREATE_RESEARCH
    )
    research_object, _revision = create_object(
        session,
        project_id=project_id,
        kind=payload.kind,
        title=payload.title,
        content_md=payload.content_md,
        rationale=payload.rationale,
        proof=payload.proof_sketch,
        attempt=payload.attempt,
        author=user,
    )
    return _object_read(session, research_object)


@router.get(
    "/projects/{project_id}/contributions/{entity_type}/{entity_id}",
    response_model=AgentContributionRead,
    operation_id="getAgentContributionProvenance",
    tags=["research"],
)
def get_agent_contribution_provenance(
    project_id: UUID,
    entity_type: ContributionEntityType,
    entity_id: UUID,
    session: DbSession,
    user: CurrentUser,
) -> AgentContributionRead:
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.VIEW
    )
    fields = {
        "RESEARCH_OBJECT": SqlContributionEntityLink.object_id,
        "OBJECT_VERSION": SqlContributionEntityLink.revision_id,
        "OBJECT_VERSION_RELATIONSHIP": SqlContributionEntityLink.relation_id,
        "RESEARCH_COMMENT": SqlContributionEntityLink.comment_id,
    }
    contribution = session.scalar(
        select(SqlContributionEnvelope)
        .join(
            SqlContributionEntityLink,
            SqlContributionEntityLink.envelope_id == SqlContributionEnvelope.id,
        )
        .where(
            SqlContributionEnvelope.project_id == project_id,
            SqlContributionEnvelope.actor_kind == ContributionActorKind.AGENT,
            fields[entity_type] == entity_id,
        )
    )
    if contribution is None or contribution.decided_by_user_id is None:
        raise ProjectNotFound
    return AgentContributionRead(
        canonical_entity_id=entity_id,
        canonical_entity_type=entity_type,
        deciding_user_id=contribution.decided_by_user_id,
        created_at=contribution.created_at,
    )


def list_research_objects(
    project_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[ResearchObjectRead]:
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.VIEW
    )
    research_objects = session.scalars(
        select(SqlResearchObject)
        .where(SqlResearchObject.project_id == project_id)
        .order_by(SqlResearchObject.created_at, SqlResearchObject.id)
    )
    return paginated(
        [_object_read(session, research_object) for research_object in research_objects],
        page,
        response,
    )


def get_project_research_object(
    project_id: UUID, object_id: UUID, session: DbSession, user: CurrentUser
) -> ResearchObjectRead:
    project_policy.require_scope(
        SqlAlchemyTransaction(session), project_id, user.id, ProjectAction.VIEW
    )
    return _object_read(
        session, object_in_project(session, project_id=project_id, object_id=object_id)
    )


def list_object_revisions(
    object_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[RevisionRead]:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.VIEW
    )
    return paginated(
        [
            _revision_read(session, item)
            for item in revisions_for_object(session, object_id=research_object.id)
        ],
        page,
        response,
    )


def post_object_revision(
    object_id: UUID, payload: RevisionCreate, session: DbSession, user: CurrentUser
) -> ResearchObjectRead:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.CREATE_RESEARCH
    )
    require_project_write(human_actor(user.id), project_id=research_object.project_id)
    research_object, _revision = create_revision(
        session,
        project_id=research_object.project_id,
        object_id=research_object.id,
        base_revision_id=payload.base_revision_id,
        title=payload.title,
        content_md=payload.content_md,
        rationale=payload.rationale,
        proof=payload.proof_sketch,
        attempt=payload.attempt,
        author=user,
    )
    return _object_read(session, research_object)


def list_object_relations(
    object_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[RelationRead]:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.VIEW
    )
    return paginated(
        [
            _relation_read(session, item)
            for item in relations_for_object(session, object_id=research_object.id)
        ],
        page,
        response,
    )


def post_object_relation(
    object_id: UUID, payload: RelationCreate, session: DbSession, user: CurrentUser
) -> RelationRead:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.CREATE_RESEARCH
    )
    require_project_write(human_actor(user.id), project_id=research_object.project_id)
    # The object-scoped route is intentionally a guardrail: source must belong
    # to that object, preventing a caller from using an arbitrary object URL as
    # a project-wide relation writer.
    revision_in_project(
        session,
        project_id=research_object.project_id,
        revision_id=payload.source_revision_id,
        object_id=research_object.id,
    )
    relation = create_relation(
        session,
        project_id=research_object.project_id,
        source_revision_id=payload.source_revision_id,
        target_revision_id=payload.target_revision_id,
        relation_type=payload.relation_type,
        rationale=payload.rationale,
        author=user,
    )
    return _relation_read(session, relation)


def list_object_comments(
    object_id: UUID, session: DbSession, user: CurrentUser, page: Page, response: Response
) -> list[CommentRead]:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.VIEW
    )
    return paginated(
        [
            _comment_read(session, item)
            for item in comments_for_object(session, object_id=research_object.id)
        ],
        page,
        response,
    )


def post_object_comment(
    object_id: UUID, payload: CommentCreate, session: DbSession, user: CurrentUser
) -> CommentRead:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.COMMENT
    )
    require_project_write(human_actor(user.id), project_id=research_object.project_id)
    comment = create_comment(
        session,
        project_id=research_object.project_id,
        object_id=research_object.id,
        revision_id=payload.revision_id,
        body_md=payload.body_md,
        author=user,
    )
    return _comment_read(session, comment)


@router.get(
    "/objects/{object_id}/neighborhood",
    response_model=VersionNeighborhoodRead,
    operation_id="getObjectNeighborhood",
    tags=["research"],
)
def get_object_neighborhood(
    object_id: UUID,
    session: DbSession,
    user: CurrentUser,
    object_version_id: UUID | None = None,
) -> VersionNeighborhoodRead:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.VIEW
    )
    selected = object_version_id or research_object.current_revision_id
    if selected is None:
        raise ProjectNotFound
    revision_in_project(
        session, project_id=research_object.project_id, revision_id=selected, object_id=object_id
    )
    relations = neighborhood(session, project_id=research_object.project_id, revision_id=selected)
    nodes = _neighborhood_nodes(
        session,
        project_id=research_object.project_id,
        selected_revision_id=selected,
        relations=relations,
    )
    return VersionNeighborhoodRead(
        object_version_id=selected,
        relationships=relationship_reads(session, [item.id for item in relations], public=False),
        nodes=[
            VersionNeighborhoodNodeRead(
                object_version_id=item.id, object_id=item.object_id, title=item.title
            )
            for item in nodes
        ],
    )


@router.get(
    "/objects/{object_id}/dependents",
    response_model=list[ObjectVersionRelationshipRead],
    operation_id="listObjectDependents",
    tags=["research"],
)
def list_object_dependents(
    object_id: UUID,
    session: DbSession,
    user: CurrentUser,
    page: Page,
    response: Response,
    object_version_id: UUID | None = None,
) -> list[ObjectVersionRelationshipRead]:
    research_object = _object_scope(
        session, object_id=object_id, user=user, action=ProjectAction.VIEW
    )
    selected = object_version_id or research_object.current_revision_id
    if selected is None:
        raise ProjectNotFound
    revision_in_project(
        session, project_id=research_object.project_id, revision_id=selected, object_id=object_id
    )
    return paginated(
        relationship_reads(
            session,
            [
                item.id
                for item in dependents(
                    session, project_id=research_object.project_id, revision_id=selected
                )
            ],
            public=False,
        ),
        page,
        response,
    )

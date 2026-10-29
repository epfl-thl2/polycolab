"""Account, project, membership, and gateway profile endpoints."""

from __future__ import annotations

from dataclasses import replace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.actors import Actor, human_actor
from polycolab.access.authorization import (
    ProjectAction,
    ProjectNotFound,
    project_policy,
    require_manage_credentials,
    require_manage_members,
    require_project_management,
)
from polycolab.accounts.schemas import UserRead
from polycolab.agents.sessions import archive_project_agent_sessions
from polycolab.app.dependencies import CurrentActor, CurrentUser, DbSession, Page, paginated
from polycolab.db.converters.projects import invitation as invitation_entity
from polycolab.db.models import (
    SqlInvitation,
    SqlLocalAccount,
    SqlMembership,
    SqlUser,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.projects import Membership as MembershipEntity
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
from polycolab.projects.projections import (
    _member_read as _member_read,
)
from polycolab.projects.projections import (
    _public_project as _public_project,
)
from polycolab.projects.projections import (
    _public_project_read as _public_project_read,
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

router = APIRouter(prefix="/api/v1")
ModerationRetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def _user_for_actor(session: Session, actor: Actor) -> SqlUser:
    if actor.human_user_id is None:
        raise ProjectNotFound
    user = session.get(SqlUser, actor.human_user_id)
    if user is None:
        raise ProjectNotFound
    return user


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


@router.get("/users/me", response_model=UserRead, operation_id="getCurrentUser", tags=["users"])
def get_current_user(user: CurrentUser, response: Response) -> UserRead:
    response.headers["Cache-Control"] = "private, no-store"
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


@router.post(
    "/projects",
    response_model=ProjectMemberRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProject",
    tags=["projects"],
)
def post_project(
    payload: ProjectCreate, session: DbSession, actor: CurrentActor
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
        workspace_mode=payload.workspace_mode,
    )
    membership = project_policy.membership(SqlAlchemyTransaction(session), project.id, user.id)
    assert membership is not None
    return _member_read(
        project, membership, member_counts(SqlAlchemyTransaction(session), [project.id])[project.id]
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

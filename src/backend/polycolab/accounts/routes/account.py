"""Human account and private provider profile endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from polycolab.access.actors import human_actor
from polycolab.access.authorization import ProjectNotFound, require_manage_credentials
from polycolab.accounts.schemas import UserRead
from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.db.models import SqlProviderProfile
from polycolab.model_gateway.schemas import (
    ProviderProfileCreate,
    ProviderProfileRead,
    ProviderProfileRotate,
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

router = APIRouter(prefix="/api/v1")


@router.get("/account", response_model=UserRead, operation_id="getAccount", tags=["account"])
def get_current_user(user: CurrentUser, response: Response) -> UserRead:
    response.headers["Cache-Control"] = "private, no-store"
    return UserRead.model_validate(user)


def _provider_profile_read(profile: SqlProviderProfile) -> ProviderProfileRead:
    return ProviderProfileRead.model_validate(profile)


@router.post(
    "/account/provider-profiles",
    response_model=ProviderProfileRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProviderProfile",
    tags=["provider-profiles"],
)
def post_provider_profile(
    payload: ProviderProfileCreate, request: Request, session: DbSession, user: CurrentUser
) -> ProviderProfileRead:
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
    return _provider_profile_read(profile)


@router.get(
    "/account/provider-profiles",
    response_model=list[ProviderProfileRead],
    operation_id="listProviderProfiles",
    tags=["provider-profiles"],
)
def list_provider_profiles(
    response: Response, page: Page, session: DbSession, user: CurrentUser
) -> list[ProviderProfileRead]:
    profiles = [
        _provider_profile_read(profile)
        for profile in session.scalars(
            select(SqlProviderProfile)
            .where(SqlProviderProfile.user_id == user.id, SqlProviderProfile.deleted_at.is_(None))
            .order_by(SqlProviderProfile.created_at.desc(), SqlProviderProfile.id.desc())
        )
    ]
    return paginated(profiles, page, response)


@router.post(
    "/account/provider-profiles/{profile_id}/rotate",
    response_model=ProviderProfileRead,
    operation_id="rotateProviderProfile",
    tags=["provider-profiles"],
)
def post_provider_profile_rotate(
    profile_id: UUID,
    payload: ProviderProfileRotate,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> ProviderProfileRead:
    require_manage_credentials(human_actor(user.id))
    try:
        return _provider_profile_read(
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
    "/account/provider-profiles/{profile_id}/validate",
    response_model=ProviderProfileRead,
    operation_id="validateProviderProfile",
    tags=["provider-profiles"],
)
def post_provider_profile_validate(
    profile_id: UUID, request: Request, session: DbSession, user: CurrentUser
) -> ProviderProfileRead:
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
    return _provider_profile_read(profile)


@router.delete(
    "/account/provider-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteProviderProfile",
    tags=["provider-profiles"],
)
def remove_provider_profile(profile_id: UUID, session: DbSession, user: CurrentUser) -> Response:
    require_manage_credentials(human_actor(user.id))
    try:
        delete_profile(session, profile_id=profile_id, user=user)
    except GatewayNotFound:
        raise ProjectNotFound from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)

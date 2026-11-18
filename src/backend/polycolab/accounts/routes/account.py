"""Human account and private provider connection endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from polycolab.access.actors import human_actor
from polycolab.access.authorization import ProjectNotFound, require_manage_credentials
from polycolab.accounts.schemas import UserRead
from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.db.models import SqlProviderConnection
from polycolab.model_gateway.schemas import (
    PlatformModelRead,
    ProviderConnectionCreate,
    ProviderConnectionRead,
    ProviderConnectionRotate,
)
from polycolab.model_gateway.service import (
    GatewayNotFound,
    ProviderFailure,
    UnsafeBaseUrl,
    connection_for_user,
    create_connection,
    delete_connection,
    rotate_connection,
    validate_connection_credential,
)

router = APIRouter(prefix="/api/v1")


@router.get("/account", response_model=UserRead, operation_id="getAccount", tags=["account"])
def get_current_user(user: CurrentUser, response: Response) -> UserRead:
    response.headers["Cache-Control"] = "private, no-store"
    return UserRead.model_validate(user)


def _provider_connection_read(connection: SqlProviderConnection) -> ProviderConnectionRead:
    return ProviderConnectionRead.model_validate(connection)


@router.post(
    "/account/provider-connections",
    response_model=ProviderConnectionRead,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProviderConnection",
    tags=["provider-connections"],
)
def post_provider_connection(
    payload: ProviderConnectionCreate, request: Request, session: DbSession, user: CurrentUser
) -> ProviderConnectionRead:
    require_manage_credentials(human_actor(user.id))
    wrapper = request.app.state.credential_wrapper
    try:
        connection = create_connection(
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
    return _provider_connection_read(connection)


@router.get(
    "/account/provider-connections",
    response_model=list[ProviderConnectionRead],
    operation_id="listProviderConnections",
    tags=["provider-connections"],
)
def list_provider_connections(
    response: Response, page: Page, session: DbSession, user: CurrentUser
) -> list[ProviderConnectionRead]:
    connections = [
        _provider_connection_read(connection)
        for connection in session.scalars(
            select(SqlProviderConnection)
            .where(
                SqlProviderConnection.user_id == user.id, SqlProviderConnection.deleted_at.is_(None)
            )
            .order_by(SqlProviderConnection.created_at.desc(), SqlProviderConnection.id.desc())
        )
    ]
    return paginated(connections, page, response)


@router.post(
    "/account/provider-connections/{provider_connection_id}/rotate",
    response_model=ProviderConnectionRead,
    operation_id="rotateProviderConnection",
    tags=["provider-connections"],
)
def post_provider_connection_rotate(
    provider_connection_id: UUID,
    payload: ProviderConnectionRotate,
    request: Request,
    session: DbSession,
    user: CurrentUser,
) -> ProviderConnectionRead:
    require_manage_credentials(human_actor(user.id))
    try:
        return _provider_connection_read(
            rotate_connection(
                session,
                provider_connection_id=provider_connection_id,
                user=user,
                wrapper=request.app.state.credential_wrapper,
                api_key=payload.api_key.get_secret_value(),
            )
        )
    except GatewayNotFound:
        raise ProjectNotFound from None


@router.post(
    "/account/provider-connections/{provider_connection_id}/validate",
    response_model=ProviderConnectionRead,
    operation_id="validateProviderConnection",
    tags=["provider-connections"],
)
def post_provider_connection_validate(
    provider_connection_id: UUID, request: Request, session: DbSession, user: CurrentUser
) -> ProviderConnectionRead:
    require_manage_credentials(human_actor(user.id))
    try:
        connection = connection_for_user(
            session, provider_connection_id=provider_connection_id, user_id=user.id
        )
        validate_connection_credential(
            connection=connection,
            user_id=user.id,
            wrapper=request.app.state.credential_wrapper,
            transport=request.app.state.provider_transport,
        )
    except GatewayNotFound:
        raise ProjectNotFound from None
    except UnsafeBaseUrl, ProviderFailure:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from None
    return _provider_connection_read(connection)


@router.delete(
    "/account/provider-connections/{provider_connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteProviderConnection",
    tags=["provider-connections"],
)
def remove_provider_connection(
    provider_connection_id: UUID, session: DbSession, user: CurrentUser
) -> Response:
    require_manage_credentials(human_actor(user.id))
    try:
        delete_connection(session, provider_connection_id=provider_connection_id, user=user)
    except GatewayNotFound:
        raise ProjectNotFound from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/platform-models",
    response_model=list[PlatformModelRead],
    operation_id="listPlatformModels",
    tags=["models"],
)
def list_platform_models(
    request: Request, response: Response, user: CurrentUser
) -> list[PlatformModelRead]:
    response.headers["Cache-Control"] = "private, no-store"
    settings = request.app.state.settings
    catalog = settings.model_catalog
    return [
        PlatformModelRead(
            id=model.connection_id,
            catalog_id=model.id,
            display_name=model.label,
            model_id=model.model,
            uses=model.uses,
            harnesses=[
                harness
                for harness in model.harnesses
                if (
                    (
                        settings.runtime_codex_image is not None
                        and catalog.providers[model.provider].wire_api == "responses"
                    )
                    or (
                        settings.runtime_codex_image is None
                        and harness == "platform"
                        and catalog.providers[model.provider].wire_api == "chat_completions"
                    )
                )
            ],
            default_for=[
                use
                for use, identifier in catalog.defaults.model_dump().items()
                if identifier == model.id
            ],
        )
        for model in catalog.models
    ]

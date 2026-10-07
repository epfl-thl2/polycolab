"""Browser authentication endpoints for the built-in account provider."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import (
    AccountNotFound,
    RegistrationClosed,
    RegistrationInvitationInvalid,
    RegistrationRequestInvalid,
    account_count,
    account_for_session,
    auth_session_for_token,
    authenticate_account,
    create_session,
    issue_registration_invitation,
    reauthenticate_session_with_password,
    register_account,
    registration_invitations,
    revoke_registration_invitation,
    revoke_session,
)
from polycolab.accounts.providers import SocialAuthenticationFailed, SocialProvider
from polycolab.accounts.social import (
    SocialAuthConflict,
    SocialAuthInvalid,
    SocialReauthenticationRequired,
    consume_social_flow,
    create_social_flow,
    delete_consumed_social_flow,
    link_social_identity,
    linked_social_providers,
    purge_expired_social_transactions,
    resolve_social_sign_in,
    unlink_social_identity,
)
from polycolab.db.models import SqlLocalAccount, SqlRegistrationInvitation
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.accounts import LocalAccount as LocalAccountEntity
from polycolab.entities.accounts import RegistrationInvitation as RegistrationInvitationEntity
from polycolab.entities.enums import InvitationStatus, SocialAuthPurpose, SocialProviderKind
from polycolab.entities.time import utc_now
from polycolab.execution.limits import enforce_login_username_limit
from polycolab.platform.config import AuthMode, RegistrationMode


class AccountCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AccountRegistration(AccountCredentials):
    display_name: str | None = Field(default=None, max_length=200)
    invitation_code: SecretStr | None = Field(default=None, min_length=32, max_length=128)


class RegistrationInvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SocialStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_path: str = Field(default="/", min_length=1, max_length=500)


class PasswordReauthentication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


router = APIRouter(prefix="/auth", include_in_schema=False)
_SOCIAL_FLOW_COOKIE = "polycolab_social_flow"


def _require_local(request: Request) -> None:
    if request.app.state.settings.auth_mode is not AuthMode.LOCAL:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _session(request: Request) -> Session:
    factory = cast(Callable[[], Session], request.app.state.session_factory)
    return factory()


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.local_auth_cookie_name,
        token,
        max_age=settings.local_auth_session_ttl_seconds,
        httponly=True,
        secure=settings.app_env.value != "local",
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(request: Request, response: Response) -> None:
    response.delete_cookie(request.app.state.settings.local_auth_cookie_name, path="/")


def _require_same_origin(request: Request) -> None:
    try:
        expected = request.app.state.settings.public_origin
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    if request.headers.get("Origin") != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin_mismatch")


def _social_provider(request: Request, provider: str) -> tuple[SocialProviderKind, SocialProvider]:
    _require_local(request)
    try:
        kind = SocialProviderKind(provider)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    configured = request.app.state.social_providers.get(kind)
    if configured is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return kind, configured


def _set_social_flow_cookie(request: Request, response: Response, value: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        _SOCIAL_FLOW_COOKIE,
        value,
        max_age=settings.social_auth_transaction_ttl_seconds,
        httponly=True,
        secure=settings.public_origin.startswith("https://"),
        samesite="lax",
        path="/auth/social",
    )


def _clear_social_flow_cookie(response: Response) -> None:
    response.delete_cookie(_SOCIAL_FLOW_COOKIE, path="/auth/social")


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"


def _callback_response(return_path: str, outcome: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{return_path}?social_auth={outcome}", status_code=status.HTTP_303_SEE_OTHER
    )
    _clear_social_flow_cookie(response)
    _no_store(response)
    return response


def _account_read(account: SqlLocalAccount | LocalAccountEntity) -> dict[str, object]:
    # Keep this response deliberately smaller than the persistence model.
    return {
        "authenticated": True,
        "username": account.username,
        "display_name": account.display_name or account.username,
        "is_admin": account.is_admin,
    }


def _current_admin(request: Request, session: Session) -> LocalAccountEntity:
    token = request.cookies.get(request.app.state.settings.local_auth_cookie_name)
    account = account_for_session(SqlAlchemyTransaction(session), token) if token else None
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if not account.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return account


def _registration_invitation_read(
    invitation: SqlRegistrationInvitation | RegistrationInvitationEntity,
    *,
    include_code: str | None = None,
) -> dict[str, object]:
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    status_value = invitation.status.value.casefold()
    if invitation.status is InvitationStatus.PENDING and expires_at <= utc_now():
        status_value = "expired"
    result: dict[str, object] = {
        "id": invitation.id,
        "status": status_value,
        "expires_at": invitation.expires_at,
        "created_at": invitation.created_at,
    }
    if include_code is not None:
        result["code"] = include_code
    return result


@router.get("/config")
def auth_config(request: Request) -> dict[str, object]:
    """Return only browser-safe, provider-neutral authentication metadata."""

    settings = request.app.state.settings
    configuration: dict[str, object] = {"mode": settings.auth_mode.value}
    if settings.auth_mode is AuthMode.LOCAL:
        configuration["social_providers"] = list(settings.social_provider_names)
        configuration["registration_mode"] = settings.registration_mode.value
    if settings.auth_mode is AuthMode.OIDC:
        configuration.update(
            {
                "issuer": str(settings.oidc_issuer).rstrip("/")
                if settings.oidc_issuer is not None
                else None,
                "client_id": settings.oidc_client_id,
                "audience": settings.oidc_audience,
            }
        )
    return configuration


@router.get("/me")
def me(request: Request) -> dict[str, object]:
    _require_local(request)
    session = _session(request)
    token = request.cookies.get(request.app.state.settings.local_auth_cookie_name)
    if not token:
        try:
            return {"authenticated": False}
        finally:
            session.close()
    try:
        account = account_for_session(SqlAlchemyTransaction(session), token)
        if account is None:
            return {"authenticated": False}
        return _account_read(account)
    finally:
        session.close()


@router.post("/setup", include_in_schema=False)
def removed_setup() -> None:
    """Do not let the SPA fallback reveal a method-specific setup surface."""

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: AccountRegistration, request: Request, response: Response
) -> dict[str, object]:
    _require_local(request)
    settings = request.app.state.settings
    if settings.registration_mode is RegistrationMode.CLOSED:
        raise RegistrationClosed
    _require_same_origin(request)
    raw_invitation = (
        payload.invitation_code.get_secret_value() if payload.invitation_code is not None else None
    )
    if settings.registration_mode is RegistrationMode.OPEN and raw_invitation is not None:
        raise RegistrationRequestInvalid
    if settings.registration_mode is RegistrationMode.INVITATION and raw_invitation is None:
        raise RegistrationInvitationInvalid
    session = _session(request)
    try:
        account, token = register_account(
            SqlAlchemyTransaction(session),
            username=payload.username,
            password=payload.password,
            display_name=payload.display_name,
            invitation_code=raw_invitation,
            session_ttl_seconds=settings.local_auth_session_ttl_seconds,
        )
        _set_session_cookie(request, response, token)
        _no_store(response)
        return _account_read(account)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    finally:
        session.close()


@router.post("/registration/invitations", status_code=status.HTTP_201_CREATED)
def create_registration_invitation(
    _: RegistrationInvitationCreate, request: Request, response: Response
) -> dict[str, object]:
    _require_local(request)
    _require_same_origin(request)
    if request.app.state.settings.registration_mode is not RegistrationMode.INVITATION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    session = _session(request)
    try:
        admin = _current_admin(request, session)
        issued = issue_registration_invitation(
            SqlAlchemyTransaction(session),
            created_by_account_id=admin.id,
            ttl_seconds=request.app.state.settings.registration_invitation_ttl_seconds,
        )
        _no_store(response)
        return _registration_invitation_read(issued.invitation, include_code=issued.code)
    finally:
        session.close()


@router.get("/registration/invitations")
def list_registration_invitations(
    request: Request, response: Response, limit: int = Query(default=50, ge=1, le=100)
) -> list[dict[str, object]]:
    _require_local(request)
    if request.app.state.settings.registration_mode is not RegistrationMode.INVITATION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    session = _session(request)
    try:
        _current_admin(request, session)
        result = [
            _registration_invitation_read(item)
            for item in registration_invitations(SqlAlchemyTransaction(session), limit=limit)
        ]
        _no_store(response)
        return result
    finally:
        session.close()


@router.delete("/registration/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_registration_invitation(
    invitation_id: UUID, request: Request, response: Response
) -> None:
    _require_local(request)
    _require_same_origin(request)
    if request.app.state.settings.registration_mode is not RegistrationMode.INVITATION:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    session = _session(request)
    try:
        _current_admin(request, session)
        revoke_registration_invitation(SqlAlchemyTransaction(session), invitation_id)
        _no_store(response)
    finally:
        session.close()


@router.post("/login")
def login(payload: AccountCredentials, request: Request, response: Response) -> dict[str, object]:
    _require_local(request)
    session = _session(request)
    try:
        settings = request.app.state.settings
        enforce_login_username_limit(
            session,
            username=payload.username,
            hmac_key=settings.admission_hmac_key,
            limit=settings.login_username_requests_per_minute,
            now=utc_now(),
        )
        session.commit()
        try:
            account = authenticate_account(
                SqlAlchemyTransaction(session), username=payload.username, password=payload.password
            )
        except AccountNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_credentials",
                headers={"WWW-Authenticate": "Session"},
            ) from exc
        token = create_session(
            SqlAlchemyTransaction(session),
            account_id=account.id,
            ttl_seconds=settings.local_auth_session_ttl_seconds,
        )
        _set_session_cookie(request, response, token)
        return _account_read(account)
    finally:
        session.close()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    _require_local(request)
    token = request.cookies.get(request.app.state.settings.local_auth_cookie_name)
    if token:
        session = _session(request)
        try:
            revoke_session(SqlAlchemyTransaction(session), token)
        finally:
            session.close()
    _clear_session_cookie(request, response)


@router.post("/reauthenticate")
def reauthenticate(payload: PasswordReauthentication, request: Request) -> dict[str, bool]:
    _require_local(request)
    _require_same_origin(request)
    token = request.cookies.get(request.app.state.settings.local_auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    session = _session(request)
    try:
        try:
            reauthenticate_session_with_password(
                SqlAlchemyTransaction(session), token=token, password=payload.password
            )
        except AccountNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials"
            ) from exc
        return {"reauthenticated": True}
    finally:
        session.close()


def _start_social_flow(
    *,
    payload: SocialStart,
    request: Request,
    response: Response,
    provider: str,
    purpose: SocialAuthPurpose,
) -> dict[str, object]:
    kind, adapter = _social_provider(request, provider)
    _require_same_origin(request)
    settings = request.app.state.settings
    session = _session(request)
    try:
        purge_expired_social_transactions(session)
        if account_count(SqlAlchemyTransaction(session)) == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="setup_required")
        token = request.cookies.get(settings.local_auth_cookie_name)
        flow = create_social_flow(
            session,
            provider=kind,
            purpose=purpose,
            return_path=payload.return_path,
            ttl_seconds=settings.social_auth_transaction_ttl_seconds,
            session_token=token,
            reauthentication_seconds=settings.social_link_reauthentication_seconds,
        )
    except SocialReauthenticationRequired as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="reauth_required"
        ) from exc
    except SocialAuthInvalid as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    finally:
        session.close()
    authorization_url = adapter.authorization_url(
        state=flow.state, verifier=flow.pkce_verifier, nonce=flow.nonce
    )
    _set_social_flow_cookie(request, response, flow.browser_binding)
    _no_store(response)
    return {
        "provider": kind.value,
        "authorization_url": authorization_url,
        "expires_at": flow.expires_at,
    }


@router.post("/social/{provider}/start")
def start_social_sign_in(
    provider: str, payload: SocialStart, request: Request, response: Response
) -> dict[str, object]:
    return _start_social_flow(
        payload=payload,
        request=request,
        response=response,
        provider=provider,
        purpose=SocialAuthPurpose.SIGN_IN,
    )


@router.post("/social/{provider}/link/start")
def start_social_link(
    provider: str, payload: SocialStart, request: Request, response: Response
) -> dict[str, object]:
    return _start_social_flow(
        payload=payload,
        request=request,
        response=response,
        provider=provider,
        purpose=SocialAuthPurpose.LINK,
    )


@router.get("/social/{provider}/callback")
def social_callback(
    provider: str,
    request: Request,
    state_value: str | None = Query(default=None, alias="state"),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None, max_length=200),
) -> RedirectResponse:
    kind, adapter = _social_provider(request, provider)
    binding = request.cookies.get(_SOCIAL_FLOW_COOKIE)
    if not binding or state_value is None or not 32 <= len(state_value) <= 128:
        return _callback_response("/", "failed")
    settings = request.app.state.settings
    token = request.cookies.get(settings.local_auth_cookie_name)
    session = _session(request)
    try:
        try:
            flow = consume_social_flow(
                session,
                provider=kind,
                state=state_value,
                browser_binding=binding,
                session_token=token,
                reauthentication_seconds=settings.social_link_reauthentication_seconds,
            )
        except SocialAuthInvalid, SocialReauthenticationRequired:
            return _callback_response("/", "failed")
    finally:
        session.close()

    try:
        if error is not None or code is None or not 1 <= len(code) <= 16_384:
            return _callback_response(flow.return_path, "failed")
        try:
            provider_identity = adapter.exchange(
                code=code,
                verifier=flow.pkce_verifier,
                nonce=flow.nonce,
            )
        except SocialAuthenticationFailed:
            return _callback_response(flow.return_path, "failed")
        session = _session(request)
        try:
            if flow.purpose is SocialAuthPurpose.SIGN_IN:
                account = resolve_social_sign_in(
                    session,
                    flow=flow,
                    subject=provider_identity.subject,
                    display_name=provider_identity.display_name,
                )
            else:
                if token is None:
                    raise SocialReauthenticationRequired
                account = link_social_identity(
                    session,
                    flow=flow,
                    subject=provider_identity.subject,
                    session_token=token,
                    reauthentication_seconds=settings.social_link_reauthentication_seconds,
                )
            session_token = create_session(
                SqlAlchemyTransaction(session),
                account_id=account.id,
                ttl_seconds=settings.local_auth_session_ttl_seconds,
                password_authenticated=False,
            )
        except SocialAuthInvalid, SocialAuthConflict, SocialReauthenticationRequired:
            session.rollback()
            return _callback_response(flow.return_path, "failed")
        finally:
            session.close()
        response = _callback_response(flow.return_path, "success")
        _set_session_cookie(request, response, session_token)
        return response
    finally:
        cleanup = _session(request)
        try:
            delete_consumed_social_flow(cleanup, flow.transaction_id)
        finally:
            cleanup.close()


@router.get("/social/identities")
def social_identities(request: Request) -> dict[str, object]:
    _require_local(request)
    settings = request.app.state.settings
    token = request.cookies.get(settings.local_auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    session = _session(request)
    try:
        auth_session = auth_session_for_token(SqlAlchemyTransaction(session), token)
        if auth_session is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        account = session.get(SqlLocalAccount, auth_session.account_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return {
            "configured": list(settings.social_provider_names),
            "linked": linked_social_providers(session, account_id=account.id),
            "password_enabled": account.password_digest is not None,
        }
    finally:
        session.close()


@router.post("/social/{provider}/unlink", status_code=status.HTTP_204_NO_CONTENT)
def unlink_social(provider: str, request: Request) -> None:
    kind, _ = _social_provider(request, provider)
    _require_same_origin(request)
    settings = request.app.state.settings
    token = request.cookies.get(settings.local_auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    session = _session(request)
    try:
        try:
            unlink_social_identity(
                session,
                provider=kind,
                session_token=token,
                reauthentication_seconds=settings.social_link_reauthentication_seconds,
            )
        except SocialReauthenticationRequired as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="reauth_required"
            ) from exc
        except SocialAuthInvalid as exc:
            session.rollback()
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
        except SocialAuthConflict as exc:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="last_login_method"
            ) from exc
    finally:
        session.close()

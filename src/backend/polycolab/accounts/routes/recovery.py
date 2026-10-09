"""Generated API boundary for optional built-in email verification and recovery."""

from __future__ import annotations

from collections.abc import Callable
from ipaddress import ip_address, ip_network
from typing import cast

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import auth_session_for_token
from polycolab.accounts.recovery import (
    RecoveryInvalid,
    RecoveryRateLimited,
    confirm_password_reset,
    consume_recovery_limit,
    email_state,
    request_email_change,
    request_password_reset,
    require_recent_password_reauthentication,
    resend_email_verification,
    verify_email,
)
from polycolab.accounts.schemas import (
    AccountEmailChange,
    AccountEmailRead,
    AccountRecoveryTokenRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RecoveryAccepted,
)
from polycolab.db.models import SqlAccountEmail, SqlLocalAccount
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import KeyWrapper
from polycolab.platform.config import AuthMode, Settings

router = APIRouter(prefix="/api/v1", tags=["account recovery"])


def _session(request: Request) -> Session:
    factory = cast(Callable[[], Session], request.app.state.session_factory)
    return factory()


def _settings(request: Request) -> Settings:
    settings = cast(Settings, request.app.state.settings)
    if settings.auth_mode is not AuthMode.LOCAL:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return settings


def _same_origin(request: Request, settings: Settings) -> str:
    try:
        origin = settings.public_origin
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from error
    if request.headers.get("Origin") != origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="origin_mismatch")
    return origin


def _client_address(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client is not None else "unknown"
    try:
        parsed = ip_address(peer)
    except ValueError:
        return peer
    if not any(
        parsed in ip_network(value, strict=False)
        for value in settings.admission_trusted_proxy_cidrs
    ):
        return peer
    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return peer
    candidate = forwarded.split(",", maxsplit=1)[0].strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return peer


def _account(
    request: Request, session: Session, settings: Settings, *, require_recent: bool
) -> SqlLocalAccount:
    token = request.cookies.get(settings.local_auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    observed_at = utc_now()
    auth_session = auth_session_for_token(
        SqlAlchemyTransaction(session), token, now=observed_at, for_update=require_recent
    )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication_required",
        )
    account = session.get(SqlLocalAccount, auth_session.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    if require_recent:
        try:
            require_recent_password_reauthentication(
                auth_session,
                account_id=account.id,
                max_age_seconds=settings.account_recovery_reauthentication_seconds,
                now=observed_at,
            )
        except RecoveryInvalid as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="reauth_required"
            ) from error
    return account


def _read(state: SqlAccountEmail | None) -> AccountEmailRead:
    return AccountEmailRead(
        verified_email=state.verified_email if state is not None else None,
        verified_at=state.verified_at if state is not None else None,
        pending_email=state.pending_email if state is not None else None,
        pending_requested_at=state.pending_requested_at if state is not None else None,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


@router.get("/account/email", response_model=AccountEmailRead, operation_id="getAccountEmail")
def get_account_email(request: Request, response: Response) -> AccountEmailRead:
    settings = _settings(request)
    session = _session(request)
    try:
        account = _account(request, session, settings, require_recent=False)
        _no_store(response)
        return _read(email_state(session, account.id))
    finally:
        session.close()


@router.put("/account/email", response_model=AccountEmailRead, operation_id="changeAccountEmail")
def change_account_email(
    payload: AccountEmailChange, request: Request, response: Response
) -> AccountEmailRead:
    settings = _settings(request)
    origin = _same_origin(request, settings)
    session = _session(request)
    try:
        account = _account(request, session, settings, require_recent=True)
        try:
            consume_recovery_limit(
                session,
                action="EMAIL_CHANGE",
                scope=str(account.id),
                hmac_key=settings.admission_hmac_key,
                limit=settings.account_recovery_requests_per_hour,
                now=utc_now(),
            )
        except RecoveryRateLimited:
            session.commit()
            raise
        state = request_email_change(
            session,
            account=account,
            email=payload.email,
            public_origin=origin,
            wrapper=cast(KeyWrapper, request.app.state.credential_wrapper),
        )
        _no_store(response)
        return _read(state)
    finally:
        session.close()


@router.post(
    "/account/email/resend",
    response_model=RecoveryAccepted,
    operation_id="resendAccountEmailVerification",
)
def resend_account_email(request: Request, response: Response) -> RecoveryAccepted:
    settings = _settings(request)
    origin = _same_origin(request, settings)
    session = _session(request)
    try:
        account = _account(request, session, settings, require_recent=False)
        try:
            consume_recovery_limit(
                session,
                action="EMAIL_RESEND",
                scope=str(account.id),
                hmac_key=settings.admission_hmac_key,
                limit=settings.account_recovery_requests_per_hour,
                now=utc_now(),
            )
        except RecoveryRateLimited:
            session.commit()
            raise
        resend_email_verification(
            session,
            account=account,
            public_origin=origin,
            wrapper=cast(KeyWrapper, request.app.state.credential_wrapper),
        )
        _no_store(response)
        return RecoveryAccepted()
    finally:
        session.close()


@router.post(
    "/account/email/verify",
    response_model=RecoveryAccepted,
    operation_id="verifyAccountEmail",
)
def verify_account_email(
    payload: AccountRecoveryTokenRequest, request: Request, response: Response
) -> RecoveryAccepted:
    settings = _settings(request)
    _same_origin(request, settings)
    session = _session(request)
    try:
        verify_email(session, raw_token=payload.token.get_secret_value())
        _no_store(response)
        return RecoveryAccepted()
    finally:
        session.close()


@router.post(
    "/auth/password-reset/request",
    response_model=RecoveryAccepted,
    operation_id="requestPasswordReset",
)
def request_account_password_reset(
    payload: PasswordResetRequest, request: Request, response: Response
) -> RecoveryAccepted:
    settings = _settings(request)
    origin = _same_origin(request, settings)
    session = _session(request)
    try:
        scope = f"{_client_address(request, settings)}\x00{payload.email.strip().casefold()}"
        try:
            consume_recovery_limit(
                session,
                action="PASSWORD_RESET",
                scope=scope,
                hmac_key=settings.admission_hmac_key,
                limit=settings.account_recovery_requests_per_hour,
                now=utc_now(),
            )
        except RecoveryRateLimited:
            session.commit()
            raise
        request_password_reset(
            session,
            email=payload.email,
            public_origin=origin,
            wrapper=cast(KeyWrapper, request.app.state.credential_wrapper),
        )
        session.commit()
        _no_store(response)
        return RecoveryAccepted()
    finally:
        session.close()


@router.post(
    "/auth/password-reset/confirm",
    response_model=RecoveryAccepted,
    operation_id="confirmPasswordReset",
)
def confirm_account_password_reset(
    payload: PasswordResetConfirm, request: Request, response: Response
) -> RecoveryAccepted:
    settings = _settings(request)
    _same_origin(request, settings)
    session = _session(request)
    try:
        confirm_password_reset(
            session,
            raw_token=payload.token.get_secret_value(),
            password=payload.password.get_secret_value(),
        )
        _no_store(response)
        return RecoveryAccepted()
    finally:
        session.close()

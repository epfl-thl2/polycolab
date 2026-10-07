"""Durable browser-bound social sign-in and explicit account-linking policy."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import account_id_for_session, active_session_for_account
from polycolab.accounts.providers import SocialProvider
from polycolab.db.models import (
    SqlAuthSession,
    SqlLocalAccount,
    SqlSocialAccountIdentity,
    SqlSocialAuthTransaction,
    SqlSocialIdentityAudit,
)
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import (
    SocialAuthPurpose,
    SocialIdentityAuditAction,
    SocialProviderKind,
)
from polycolab.entities.time import utc_now
from polycolab.platform.config import Environment, Settings


class SocialAuthInvalid(Exception):
    pass


class SocialAuthConflict(Exception):
    pass


class SocialReauthenticationRequired(Exception):
    pass


@dataclass(frozen=True)
class NewSocialFlow:
    transaction_id: UUID
    provider: SocialProviderKind
    purpose: SocialAuthPurpose
    state: str = field(repr=False)
    browser_binding: str = field(repr=False)
    pkce_verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    return_path: str
    expires_at: datetime


@dataclass(frozen=True)
class ConsumedSocialFlow:
    transaction_id: UUID
    provider: SocialProviderKind
    purpose: SocialAuthPurpose
    pkce_verifier: str = field(repr=False)
    nonce: str = field(repr=False)
    return_path: str
    linked_account_id: UUID | None
    linked_session_id: UUID | None
    current_account_id: UUID | None


def configured_social_providers(settings: Settings) -> dict[SocialProviderKind, SocialProvider]:
    if not settings.social_provider_names:
        return {}
    origin = settings.public_origin
    allow_loopback = settings.app_env is Environment.LOCAL
    configured: dict[SocialProviderKind, SocialProvider] = {}
    values = (
        (
            SocialProviderKind.GOOGLE,
            settings.social_google_client_id,
            settings.social_google_client_secret,
        ),
        (
            SocialProviderKind.GITHUB,
            settings.social_github_client_id,
            settings.social_github_client_secret,
        ),
    )
    for provider, client_id, client_secret in values:
        if client_id is None or client_secret is None:
            continue
        configured[provider] = SocialProvider(
            provider.value,
            client_id,
            client_secret.get_secret_value(),
            f"{origin}/auth/social/{provider.value}/callback",
            allow_loopback_http=allow_loopback,
        )
    return configured


def safe_return_path(value: str) -> str:
    if not 1 <= len(value) <= 500 or "\\" in value:
        raise SocialAuthInvalid
    parsed = urlsplit(value)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
    ):
        raise SocialAuthInvalid
    return parsed.path


def _digest(value: str) -> str:
    try:
        return hashlib.sha256(value.encode("ascii")).hexdigest()
    except UnicodeEncodeError as exc:
        raise SocialAuthInvalid from exc


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _provider(value: str | SocialProviderKind) -> SocialProviderKind:
    try:
        return SocialProviderKind(value)
    except ValueError as exc:
        raise SocialAuthInvalid from exc


def purge_expired_social_transactions(session: Session, *, now: datetime | None = None) -> int:
    observed_at = now or utc_now()
    expired_ids = (
        select(SqlSocialAuthTransaction.id)
        .where(SqlSocialAuthTransaction.expires_at <= observed_at)
        .order_by(SqlSocialAuthTransaction.expires_at, SqlSocialAuthTransaction.id)
        .limit(100)
    )
    result = session.execute(
        delete(SqlSocialAuthTransaction).where(SqlSocialAuthTransaction.id.in_(expired_ids))
    )
    session.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def create_social_flow(
    session: Session,
    *,
    provider: str | SocialProviderKind,
    purpose: SocialAuthPurpose,
    return_path: str,
    ttl_seconds: int,
    session_token: str | None = None,
    reauthentication_seconds: int = 300,
    now: datetime | None = None,
) -> NewSocialFlow:
    if type(purpose) is not SocialAuthPurpose or not 60 <= ttl_seconds <= 600:
        raise SocialAuthInvalid
    if not 60 <= reauthentication_seconds <= 900:
        raise SocialAuthInvalid
    selected_provider = _provider(provider)
    destination = safe_return_path(return_path)
    observed_at = now or utc_now()
    linked_account_id: UUID | None = None
    linked_session_id: UUID | None = None
    if purpose is SocialAuthPurpose.LINK:
        if not session_token:
            raise SocialReauthenticationRequired
        auth_session = session.scalar(
            select(SqlAuthSession).where(
                SqlAuthSession.token_digest == _digest(session_token),
                SqlAuthSession.revoked_at.is_(None),
                SqlAuthSession.expires_at > observed_at,
            )
        )
        if auth_session is None or _as_utc(auth_session.reauthenticated_at) < (
            observed_at - timedelta(seconds=reauthentication_seconds)
        ):
            raise SocialReauthenticationRequired
        linked_account_id = auth_session.account_id
        linked_session_id = auth_session.id
    state = secrets.token_urlsafe(32)
    browser_binding = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    expires_at = observed_at + timedelta(seconds=ttl_seconds)
    transaction = SqlSocialAuthTransaction(
        state_digest=_digest(state),
        browser_binding_digest=_digest(browser_binding),
        provider=selected_provider,
        purpose=purpose,
        pkce_verifier=verifier,
        nonce=nonce,
        return_path=destination,
        expires_at=expires_at,
        linked_account_id=linked_account_id,
        linked_session_id=linked_session_id,
        created_at=observed_at,
    )
    session.add(transaction)
    session.commit()
    return NewSocialFlow(
        transaction.id,
        selected_provider,
        purpose,
        state,
        browser_binding,
        verifier,
        nonce,
        destination,
        expires_at,
    )


def consume_social_flow(
    session: Session,
    *,
    provider: str | SocialProviderKind,
    state: str,
    browser_binding: str,
    session_token: str | None,
    reauthentication_seconds: int,
    now: datetime | None = None,
) -> ConsumedSocialFlow:
    if not 60 <= reauthentication_seconds <= 900:
        raise SocialAuthInvalid
    selected_provider = _provider(provider)
    observed_at = now or utc_now()
    transaction = session.scalar(
        select(SqlSocialAuthTransaction)
        .where(SqlSocialAuthTransaction.state_digest == _digest(state))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        transaction is None
        or transaction.provider is not selected_provider
        or transaction.consumed_at is not None
        or _as_utc(transaction.expires_at) <= observed_at
        or not secrets.compare_digest(transaction.browser_binding_digest, _digest(browser_binding))
    ):
        session.rollback()
        raise SocialAuthInvalid
    current_account_id = (
        account_id_for_session(SqlAlchemyTransaction(session), session_token, now=observed_at)
        if session_token
        else None
    )
    if transaction.purpose is SocialAuthPurpose.LINK:
        if (
            not session_token
            or transaction.linked_account_id is None
            or transaction.linked_session_id is None
        ):
            session.rollback()
            raise SocialReauthenticationRequired
        auth_session = active_session_for_account(
            SqlAlchemyTransaction(session),
            token=session_token,
            account_id=transaction.linked_account_id,
            now=observed_at,
            reauthenticated_after=observed_at - timedelta(seconds=reauthentication_seconds),
            for_update=True,
        )
        if auth_session is None or auth_session.id != transaction.linked_session_id:
            session.rollback()
            raise SocialReauthenticationRequired
    transaction.consumed_at = observed_at
    session.commit()
    return ConsumedSocialFlow(
        transaction.id,
        transaction.provider,
        transaction.purpose,
        transaction.pkce_verifier,
        transaction.nonce,
        transaction.return_path,
        transaction.linked_account_id,
        transaction.linked_session_id,
        current_account_id,
    )


def delete_consumed_social_flow(session: Session, transaction_id: UUID) -> None:
    session.execute(
        delete(SqlSocialAuthTransaction).where(
            SqlSocialAuthTransaction.id == transaction_id,
            SqlSocialAuthTransaction.consumed_at.is_not(None),
        )
    )
    session.commit()


def _identity(
    session: Session, provider: SocialProviderKind, subject: str
) -> SqlSocialAccountIdentity | None:
    return session.scalar(
        select(SqlSocialAccountIdentity).where(
            SqlSocialAccountIdentity.provider == provider,
            SqlSocialAccountIdentity.subject == subject,
        )
    )


def _validate_identity_subject(subject: str) -> str:
    if not isinstance(subject, str) or not 1 <= len(subject) <= 255:
        raise SocialAuthInvalid
    return subject


def _display_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:200] or None


def resolve_social_sign_in(
    session: Session,
    *,
    flow: ConsumedSocialFlow,
    subject: str,
    display_name: str | None,
) -> SqlLocalAccount:
    if flow.purpose is not SocialAuthPurpose.SIGN_IN:
        raise SocialAuthInvalid
    identity_subject = _validate_identity_subject(subject)
    for _ in range(3):
        identity = _identity(session, flow.provider, identity_subject)
        if identity is not None:
            if identity.unlinked_at is not None:
                raise SocialAuthConflict
            if (
                flow.current_account_id is not None
                and flow.current_account_id != identity.account_id
            ):
                raise SocialAuthConflict
            account = session.get(SqlLocalAccount, identity.account_id)
            if account is None:
                raise SocialAuthInvalid
            return account
        if flow.current_account_id is not None:
            raise SocialAuthConflict
        if int(session.scalar(select(func.count()).select_from(SqlLocalAccount)) or 0) == 0:
            raise SocialAuthConflict
        account = SqlLocalAccount(
            id=uuid4(),
            username=f"social-{flow.provider.value}-{secrets.token_hex(16)}",
            password_digest=None,
            display_name=_display_name(display_name),
            is_admin=False,
        )
        identity = SqlSocialAccountIdentity(
            account_id=account.id,
            provider=flow.provider,
            subject=identity_subject,
        )
        try:
            session.add_all((account, identity))
            session.flush()
            session.add(
                SqlSocialIdentityAudit(
                    identity_id=identity.id,
                    account_id=account.id,
                    actor_account_id=None,
                    action=SocialIdentityAuditAction.CREATED,
                )
            )
            session.commit()
            return account
        except IntegrityError:
            session.rollback()
            winner = _identity(session, flow.provider, identity_subject)
            if winner is not None and winner.unlinked_at is None:
                account = session.get(SqlLocalAccount, winner.account_id)
                if account is not None:
                    return account
    raise SocialAuthConflict


def link_social_identity(
    session: Session,
    *,
    flow: ConsumedSocialFlow,
    subject: str,
    session_token: str,
    reauthentication_seconds: int,
    now: datetime | None = None,
) -> SqlLocalAccount:
    if (
        flow.purpose is not SocialAuthPurpose.LINK
        or flow.linked_account_id is None
        or flow.linked_session_id is None
    ):
        raise SocialAuthInvalid
    observed_at = now or utc_now()
    auth_session = active_session_for_account(
        SqlAlchemyTransaction(session),
        token=session_token,
        account_id=flow.linked_account_id,
        now=observed_at,
        reauthenticated_after=observed_at - timedelta(seconds=reauthentication_seconds),
        for_update=True,
    )
    if auth_session is None or auth_session.id != flow.linked_session_id:
        raise SocialReauthenticationRequired
    account = session.get(SqlLocalAccount, flow.linked_account_id, with_for_update=True)
    if account is None:
        raise SocialAuthInvalid
    identity_subject = _validate_identity_subject(subject)
    identity = _identity(session, flow.provider, identity_subject)
    action = SocialIdentityAuditAction.LINKED
    if identity is not None:
        if identity.account_id != flow.linked_account_id or identity.unlinked_at is None:
            raise SocialAuthConflict
        identity.unlinked_at = None
        action = SocialIdentityAuditAction.RELINKED
    else:
        existing_provider = session.scalar(
            select(SqlSocialAccountIdentity).where(
                SqlSocialAccountIdentity.account_id == flow.linked_account_id,
                SqlSocialAccountIdentity.provider == flow.provider,
            )
        )
        if existing_provider is not None:
            raise SocialAuthConflict
        identity = SqlSocialAccountIdentity(
            id=uuid4(),
            account_id=flow.linked_account_id,
            provider=flow.provider,
            subject=identity_subject,
        )
        session.add(identity)
    try:
        session.add(
            SqlSocialIdentityAudit(
                identity_id=identity.id,
                account_id=flow.linked_account_id,
                actor_account_id=flow.linked_account_id,
                action=action,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SocialAuthConflict from exc
    return account


def unlink_social_identity(
    session: Session,
    *,
    provider: str | SocialProviderKind,
    session_token: str,
    reauthentication_seconds: int,
    now: datetime | None = None,
) -> None:
    observed_at = now or utc_now()
    digest = _digest(session_token)
    auth_session = session.scalar(
        select(SqlAuthSession)
        .where(
            SqlAuthSession.token_digest == digest,
            SqlAuthSession.revoked_at.is_(None),
            SqlAuthSession.expires_at > observed_at,
        )
        .with_for_update()
    )
    if auth_session is None or _as_utc(auth_session.reauthenticated_at) < (
        observed_at - timedelta(seconds=reauthentication_seconds)
    ):
        raise SocialReauthenticationRequired
    # Serialize the last-login-method decision across every active session for
    # the same account, not merely across requests carrying one session token.
    account = session.get(SqlLocalAccount, auth_session.account_id, with_for_update=True)
    if account is None:
        raise SocialAuthInvalid
    selected_provider = _provider(provider)
    identity = session.scalar(
        select(SqlSocialAccountIdentity)
        .where(
            SqlSocialAccountIdentity.account_id == auth_session.account_id,
            SqlSocialAccountIdentity.provider == selected_provider,
            SqlSocialAccountIdentity.unlinked_at.is_(None),
        )
        .with_for_update()
    )
    if identity is None:
        raise SocialAuthInvalid
    other_identity = session.scalar(
        select(SqlSocialAccountIdentity.id).where(
            SqlSocialAccountIdentity.account_id == account.id,
            SqlSocialAccountIdentity.id != identity.id,
            SqlSocialAccountIdentity.unlinked_at.is_(None),
        )
    )
    if account.password_digest is None and other_identity is None:
        raise SocialAuthConflict
    identity.unlinked_at = observed_at
    session.add(
        SqlSocialIdentityAudit(
            identity_id=identity.id,
            account_id=account.id,
            actor_account_id=account.id,
            action=SocialIdentityAuditAction.UNLINKED,
        )
    )
    session.commit()


def linked_social_providers(session: Session, *, account_id: UUID) -> list[str]:
    return [
        provider.value
        for provider in session.scalars(
            select(SqlSocialAccountIdentity.provider)
            .where(
                SqlSocialAccountIdentity.account_id == account_id,
                SqlSocialAccountIdentity.unlinked_at.is_(None),
            )
            .order_by(SqlSocialAccountIdentity.provider)
        )
    ]

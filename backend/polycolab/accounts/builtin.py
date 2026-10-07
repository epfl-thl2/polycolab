"""Built-in account and browser-session application operations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from polycolab.accounts.names import normalize_username as normalize_username
from polycolab.entities.accounts import AuthSession, LocalAccount, RegistrationInvitation
from polycolab.entities.accounts import IssuedRegistrationInvitation as IssuedRegistrationInvitation
from polycolab.entities.enums import InvitationStatus
from polycolab.entities.time import utc_now
from polycolab.transaction import PersistenceConflict, Transaction

_SALT_BYTES = 16
_KEY_BYTES = 32
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DUMMY_PASSWORD_DIGEST = (
    "scrypt$16384$8$1$MDAwMDAwMDAwMDAwMDAwMA$8QMrYQJXv0q3Vd9gVxVpD0Kfbm7A4cPQ1jz8VaK8WJQ"
)


class AccountAlreadyExists(Exception):
    pass


class AccountNotFound(Exception):
    pass


class RegistrationSetupRequired(Exception):
    pass


class RegistrationClosed(Exception):
    pass


class RegistrationRequestInvalid(Exception):
    pass


class RegistrationInvitationInvalid(Exception):
    pass


class RegistrationInvitationNotFound(Exception):
    pass


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("password must be between 12 and 256 characters")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if encoded is None:
        return False
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        padding = "=" * (-len(raw_salt) % 4)
        salt = base64.urlsafe_b64decode(raw_salt + padding)
        padding = "=" * (-len(raw_digest) % 4)
        expected = base64.urlsafe_b64decode(raw_digest + padding)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
        )
    except ValueError, TypeError:
        return False
    return hmac.compare_digest(actual, expected)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_account(
    transaction: Transaction,
    *,
    username: str,
    password: str,
    display_name: str | None,
    is_admin: bool = False,
) -> LocalAccount:
    normalized = normalize_username(username)
    if transaction.accounts.local_account_by_username(normalized) is not None:
        raise AccountAlreadyExists
    return transaction.accounts.create_local_account(
        username=normalized,
        password_digest=hash_password(password),
        display_name=display_name.strip() if display_name and display_name.strip() else None,
        is_admin=is_admin,
    )


def lock_account_registry(transaction: Transaction) -> None:
    """Serialize setup and registration decisions, including an empty registry."""

    transaction.accounts.lock_registry()


def account_count(transaction: Transaction) -> int:
    return transaction.accounts.account_count()


def authenticate_account(transaction: Transaction, *, username: str, password: str) -> LocalAccount:
    try:
        normalized = normalize_username(username)
    except ValueError:
        normalized = None
    account = (
        transaction.accounts.local_account_by_username(normalized)
        if normalized is not None
        else None
    )
    digest = account.password_digest if account is not None else _DUMMY_PASSWORD_DIGEST
    valid = verify_password(password, digest)
    if account is None or not valid:
        raise AccountNotFound
    return account


def bootstrap_admin(transaction: Transaction, password: str | None) -> bool:
    """Create the fixed first administrator, without changing an existing registry."""

    lock_account_registry(transaction)
    if account_count(transaction) != 0:
        return False
    if password is None:
        raise ValueError("BOOTSTRAP_ADMIN_PASSWORD is required for an empty local deployment")
    create_account(
        transaction,
        username="admin",
        password=password,
        display_name="Admin",
        is_admin=True,
    )
    transaction.commit()
    return True


def create_session(
    transaction: Transaction,
    *,
    account_id: UUID,
    ttl_seconds: int,
    now: datetime | None = None,
    password_authenticated: bool = True,
) -> str:
    token = prepare_session(
        transaction,
        account_id=account_id,
        ttl_seconds=ttl_seconds,
        now=now,
        password_authenticated=password_authenticated,
    )
    transaction.commit()
    return token


def prepare_session(
    transaction: Transaction,
    *,
    account_id: UUID,
    ttl_seconds: int,
    now: datetime | None = None,
    password_authenticated: bool = True,
) -> str:
    token = secrets.token_urlsafe(32)
    issued_at = now or utc_now()
    transaction.accounts.create_session(
        account_id=account_id,
        digest=token_digest(token),
        created_at=issued_at,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
        password_authenticated=password_authenticated,
    )
    return token


def issue_registration_invitation(
    transaction: Transaction,
    *,
    created_by_account_id: UUID,
    ttl_seconds: int,
    now: datetime | None = None,
) -> IssuedRegistrationInvitation:
    created_at = now or utc_now()
    code = secrets.token_urlsafe(32)
    invitation = transaction.accounts.create_registration_invitation(
        digest=token_digest(code),
        created_by=created_by_account_id,
        created_at=created_at,
        expires_at=created_at + timedelta(seconds=ttl_seconds),
    )
    transaction.commit()
    return IssuedRegistrationInvitation(invitation, code)


def registration_invitations(
    transaction: Transaction, *, limit: int
) -> list[RegistrationInvitation]:
    return list(transaction.accounts.registration_invitations(limit=limit))


def revoke_registration_invitation(transaction: Transaction, invitation_id: UUID) -> None:
    invitation = transaction.accounts.registration_invitation(invitation_id)
    if invitation is None:
        raise RegistrationInvitationNotFound
    if invitation.status is InvitationStatus.PENDING:
        transaction.accounts.revoke_registration_invitation(invitation.id, at=utc_now())
        transaction.commit()


def register_account(
    transaction: Transaction,
    *,
    username: str,
    password: str,
    display_name: str | None,
    invitation_code: str | None,
    session_ttl_seconds: int,
    now: datetime | None = None,
) -> tuple[LocalAccount, str]:
    """Atomically create an ordinary account, session, and optional invite use."""

    normalized = normalize_username(username)
    password_digest = hash_password(password)
    observed_at = now or utc_now()
    try:
        lock_account_registry(transaction)
        if account_count(transaction) == 0:
            raise RegistrationSetupRequired
        invitation: RegistrationInvitation | None = None
        if invitation_code is not None:
            try:
                digest = token_digest(invitation_code)
            except UnicodeEncodeError as exc:
                raise RegistrationInvitationInvalid from exc
            invitation = transaction.accounts.registration_invitation_by_digest(digest)
            expires_at = invitation.expires_at if invitation is not None else None
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if (
                invitation is None
                or invitation.status is not InvitationStatus.PENDING
                or expires_at is None
                or expires_at <= observed_at
            ):
                raise RegistrationInvitationInvalid
        if transaction.accounts.local_account_by_username(normalized):
            raise AccountAlreadyExists
        account = transaction.accounts.create_local_account(
            username=normalized,
            password_digest=password_digest,
            display_name=display_name.strip() if display_name and display_name.strip() else None,
            is_admin=False,
            at=observed_at,
        )
        token = prepare_session(
            transaction,
            account_id=account.id,
            ttl_seconds=session_ttl_seconds,
            now=observed_at,
        )
        if invitation is not None:
            transaction.accounts.accept_registration_invitation(
                invitation.id, account_id=account.id, at=observed_at
            )
        transaction.commit()
        return account, token
    except PersistenceConflict as exc:
        transaction.rollback()
        raise AccountAlreadyExists from exc
    except Exception:
        transaction.rollback()
        raise


def revoke_session(transaction: Transaction, token: str) -> None:
    auth_session = transaction.accounts.auth_session(token_digest(token), active_at=None)
    if auth_session is not None and auth_session.revoked_at is None:
        transaction.accounts.revoke_session(auth_session.id, at=utc_now())
        transaction.commit()


def account_for_session(transaction: Transaction, token: str) -> LocalAccount | None:
    auth_session = auth_session_for_token(transaction, token)
    if auth_session is None:
        return None
    return transaction.accounts.local_account(auth_session.account_id)


def auth_session_for_token(
    transaction: Transaction,
    token: str,
    *,
    now: datetime | None = None,
    for_update: bool = False,
) -> AuthSession | None:
    try:
        digest = token_digest(token)
    except UnicodeEncodeError:
        return None
    return transaction.accounts.auth_session(digest, active_at=now or utc_now(), lock=for_update)


def reauthenticate_session_with_password(
    transaction: Transaction,
    *,
    token: str,
    password: str,
    now: datetime | None = None,
) -> LocalAccount:
    observed_at = now or utc_now()
    auth_session = auth_session_for_token(transaction, token, now=observed_at, for_update=True)
    if auth_session is None:
        raise AccountNotFound
    account = transaction.accounts.local_account(auth_session.account_id)
    if account is None or not verify_password(password, account.password_digest):
        raise AccountNotFound
    transaction.accounts.reauthenticate_session(auth_session.id, at=observed_at)
    transaction.commit()
    return account


def active_session_for_account(
    transaction: Transaction,
    *,
    token: str,
    account_id: UUID,
    now: datetime,
    reauthenticated_after: datetime | None = None,
    for_update: bool = False,
) -> AuthSession | None:
    auth_session = auth_session_for_token(transaction, token, now=now, for_update=for_update)
    reauthenticated_at = auth_session.reauthenticated_at if auth_session is not None else None
    if reauthenticated_at is not None and reauthenticated_at.tzinfo is None:
        reauthenticated_at = reauthenticated_at.replace(tzinfo=UTC)
    if (
        auth_session is None
        or auth_session.account_id != account_id
        or reauthenticated_after is not None
        and (reauthenticated_at is None or reauthenticated_at < reauthenticated_after)
    ):
        return None
    return auth_session


def account_id_for_session(transaction: Transaction, token: str, *, now: datetime) -> UUID | None:
    auth_session = auth_session_for_token(transaction, token, now=now)
    return auth_session.account_id if auth_session is not None else None


def account_for_auth_session(
    transaction: Transaction, auth_session: AuthSession
) -> LocalAccount | None:
    return transaction.accounts.local_account(auth_session.account_id)


def delete_expired_sessions(transaction: Transaction) -> None:
    transaction.accounts.delete_expired_sessions(at=utc_now())
    transaction.commit()

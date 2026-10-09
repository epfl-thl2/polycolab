"""Optional built-in verified email, password recovery and protected mail queue."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from polycolab.accounts.builtin import hash_password, token_digest
from polycolab.db.models import (
    SqlAccountEmail,
    SqlAccountRecoveryRateWindow,
    SqlAccountRecoveryToken,
    SqlAuthSession,
    SqlLocalAccount,
    SqlMailOutbox,
)
from polycolab.entities.accounts import AuthSession as AuthSessionEntity
from polycolab.entities.accounts import LocalAccount as LocalAccountEntity
from polycolab.entities.enums import AccountTokenPurpose, MailOutboxStatus, MailPurpose
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    EncryptedCredential,
    KeyWrapper,
    decrypt_credential,
    encrypt_credential,
)

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=30)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class RecoveryInvalid(Exception):
    pass


class RecoveryConflict(Exception):
    pass


class RecoveryRateLimited(Exception):
    pass


class MailClaimInvalid(Exception):
    pass


@dataclass(frozen=True)
class DecryptedMail:
    recipient: str
    action_url: str
    template: str


def require_recent_password_reauthentication(
    auth_session: SqlAuthSession | AuthSessionEntity,
    *,
    account_id: UUID,
    max_age_seconds: int,
    now: datetime,
) -> None:
    observed = auth_session.password_reauthenticated_at
    if observed is not None:
        observed = _aware(observed)
    if (
        auth_session.account_id != account_id
        or observed is None
        or observed < now - timedelta(seconds=max_age_seconds)
    ):
        raise RecoveryInvalid


def normalize_recovery_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 320 or _EMAIL.fullmatch(normalized) is None:
        raise RecoveryInvalid
    return normalized


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _mail_context(row: SqlMailOutbox) -> bytes:
    return f"polycolab:mail-outbox:{row.id}:{row.account_id}:{row.purpose.value}".encode("ascii")


def _clear_mail(row: SqlMailOutbox, status: MailOutboxStatus, now: datetime) -> None:
    row.status = status
    row.encrypted_payload = None
    row.wrapped_data_key = None
    row.encryption_key_version = None
    row.claimed_by = None
    row.claimed_at = None
    row.terminal_at = now


def _cancel_token_mail(session: Session, token_ids: list[UUID], now: datetime) -> None:
    if not token_ids:
        return
    for row in session.scalars(
        select(SqlMailOutbox)
        .where(
            SqlMailOutbox.token_id.in_(token_ids),
            SqlMailOutbox.status.in_([MailOutboxStatus.PENDING, MailOutboxStatus.CLAIMED]),
        )
        .with_for_update()
    ):
        _clear_mail(row, MailOutboxStatus.CANCELLED, now)


def _invalidate_tokens(
    session: Session, account_id: UUID, purpose: AccountTokenPurpose, now: datetime
) -> None:
    rows = list(
        session.scalars(
            select(SqlAccountRecoveryToken)
            .where(
                SqlAccountRecoveryToken.account_id == account_id,
                SqlAccountRecoveryToken.purpose == purpose,
                SqlAccountRecoveryToken.consumed_at.is_(None),
                SqlAccountRecoveryToken.invalidated_at.is_(None),
            )
            .with_for_update()
        )
    )
    for row in rows:
        row.invalidated_at = now
    _cancel_token_mail(session, [row.id for row in rows], now)


def consume_recovery_limit(
    session: Session,
    *,
    action: str,
    scope: str,
    hmac_key: str,
    limit: int,
    now: datetime,
) -> None:
    window = now.replace(minute=0, second=0, microsecond=0)
    digest = hmac.new(
        hmac_key.encode("utf-8"), f"{action}\x00{scope}".encode(), hashlib.sha256
    ).hexdigest()
    row = session.scalar(
        select(SqlAccountRecoveryRateWindow)
        .where(
            SqlAccountRecoveryRateWindow.action == action,
            SqlAccountRecoveryRateWindow.scope_digest == digest,
            SqlAccountRecoveryRateWindow.window_started_at == window,
        )
        .with_for_update()
    )
    if row is None:
        try:
            with session.begin_nested():
                row = SqlAccountRecoveryRateWindow(
                    action=action, scope_digest=digest, window_started_at=window, count=0
                )
                session.add(row)
                session.flush()
        except IntegrityError:
            row = session.scalar(
                select(SqlAccountRecoveryRateWindow)
                .where(
                    SqlAccountRecoveryRateWindow.action == action,
                    SqlAccountRecoveryRateWindow.scope_digest == digest,
                    SqlAccountRecoveryRateWindow.window_started_at == window,
                )
                .with_for_update()
            )
    if row is None:
        raise RecoveryInvalid
    row.count += 1
    session.flush()
    if row.count > limit:
        raise RecoveryRateLimited


def email_state(session: Session, account_id: UUID) -> SqlAccountEmail | None:
    return session.get(SqlAccountEmail, account_id)


def _queue_mail(
    session: Session,
    *,
    account_id: UUID,
    token: SqlAccountRecoveryToken,
    raw_token: str,
    purpose: MailPurpose,
    recipient: str,
    public_origin: str,
    wrapper: KeyWrapper,
    now: datetime,
) -> SqlMailOutbox:
    row = SqlMailOutbox(
        id=uuid4(),
        account_id=account_id,
        token_id=token.id,
        purpose=purpose,
        encrypted_payload=b"pending",
        wrapped_data_key=b"pending",
        encryption_key_version="pending",
        payload_digest="0" * 64,
        expires_at=token.expires_at,
        created_at=now,
    )
    path = "verify-email" if purpose is MailPurpose.EMAIL_VERIFICATION else "reset-password"
    payload = json.dumps(
        {
            "recipient": recipient,
            "action_url": f"{public_origin.rstrip('/')}/{path}?token={raw_token}",
            "template": purpose.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    encrypted = encrypt_credential(wrapper, context=_mail_context(row), secret=payload)
    row.encrypted_payload = encrypted.ciphertext
    row.wrapped_data_key = encrypted.wrapped_key
    row.encryption_key_version = encrypted.key_version
    row.payload_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    session.add(row)
    return row


def _issue_token_and_mail(
    session: Session,
    *,
    account_id: UUID,
    email: str,
    purpose: AccountTokenPurpose,
    public_origin: str,
    wrapper: KeyWrapper,
    now: datetime,
) -> None:
    raw_token = secrets.token_urlsafe(32)
    token = SqlAccountRecoveryToken(
        id=uuid4(),
        account_id=account_id,
        purpose=purpose,
        email=email,
        token_digest=token_digest(raw_token),
        expires_at=now
        + (
            EMAIL_VERIFICATION_TTL
            if purpose is AccountTokenPurpose.EMAIL_VERIFICATION
            else PASSWORD_RESET_TTL
        ),
        created_at=now,
    )
    session.add(token)
    _queue_mail(
        session,
        account_id=account_id,
        token=token,
        raw_token=raw_token,
        purpose=MailPurpose(purpose.value),
        recipient=email,
        public_origin=public_origin,
        wrapper=wrapper,
        now=now,
    )


def request_email_change(
    session: Session,
    *,
    account: SqlLocalAccount | LocalAccountEntity,
    email: str,
    public_origin: str,
    wrapper: KeyWrapper,
    now: datetime | None = None,
) -> SqlAccountEmail:
    observed_at = now or utc_now()
    normalized = normalize_recovery_email(email)
    state = session.get(SqlAccountEmail, account.id, with_for_update=True)
    if state is None:
        state = SqlAccountEmail(
            account_id=account.id, created_at=observed_at, updated_at=observed_at
        )
        session.add(state)
    if state.verified_email == normalized:
        state.pending_email = None
        state.pending_requested_at = None
        _invalidate_tokens(session, account.id, AccountTokenPurpose.EMAIL_VERIFICATION, observed_at)
        session.commit()
        return state
    _invalidate_tokens(session, account.id, AccountTokenPurpose.EMAIL_VERIFICATION, observed_at)
    state.pending_email = normalized
    state.pending_requested_at = observed_at
    _issue_token_and_mail(
        session,
        account_id=account.id,
        email=normalized,
        purpose=AccountTokenPurpose.EMAIL_VERIFICATION,
        public_origin=public_origin,
        wrapper=wrapper,
        now=observed_at,
    )
    session.commit()
    session.refresh(state)
    return state


def resend_email_verification(
    session: Session,
    *,
    account: SqlLocalAccount | LocalAccountEntity,
    public_origin: str,
    wrapper: KeyWrapper,
    now: datetime | None = None,
) -> SqlAccountEmail:
    observed_at = now or utc_now()
    state = session.get(SqlAccountEmail, account.id, with_for_update=True)
    if state is None or state.pending_email is None:
        raise RecoveryInvalid
    _invalidate_tokens(session, account.id, AccountTokenPurpose.EMAIL_VERIFICATION, observed_at)
    state.pending_requested_at = observed_at
    _issue_token_and_mail(
        session,
        account_id=account.id,
        email=state.pending_email,
        purpose=AccountTokenPurpose.EMAIL_VERIFICATION,
        public_origin=public_origin,
        wrapper=wrapper,
        now=observed_at,
    )
    session.commit()
    session.refresh(state)
    return state


def verify_email(session: Session, *, raw_token: str, now: datetime | None = None) -> None:
    observed_at = now or utc_now()
    try:
        digest = token_digest(raw_token)
    except UnicodeEncodeError as error:
        raise RecoveryInvalid from error
    token = session.scalar(
        select(SqlAccountRecoveryToken)
        .where(SqlAccountRecoveryToken.token_digest == digest)
        .with_for_update()
    )
    if (
        token is None
        or token.purpose is not AccountTokenPurpose.EMAIL_VERIFICATION
        or token.consumed_at is not None
        or token.invalidated_at is not None
        or _aware(token.expires_at) <= observed_at
    ):
        raise RecoveryInvalid
    state = session.get(SqlAccountEmail, token.account_id, with_for_update=True)
    if state is None or state.pending_email != token.email:
        raise RecoveryInvalid
    existing = session.scalar(
        select(SqlAccountEmail).where(
            SqlAccountEmail.verified_email == token.email,
            SqlAccountEmail.account_id != token.account_id,
        )
    )
    if existing is not None:
        raise RecoveryConflict
    state.verified_email = token.email
    state.verified_at = observed_at
    state.pending_email = None
    state.pending_requested_at = None
    token.consumed_at = observed_at
    try:
        # Acquire the verified-address uniqueness constraint before subsequent
        # queries can trigger an uncaught autoflush under concurrent promotion.
        session.flush()
    except IntegrityError as error:
        session.rollback()
        raise RecoveryConflict from error
    _cancel_token_mail(session, [token.id], observed_at)
    remaining = list(
        session.scalars(
            select(SqlAccountRecoveryToken)
            .where(
                SqlAccountRecoveryToken.account_id == token.account_id,
                SqlAccountRecoveryToken.purpose == AccountTokenPurpose.EMAIL_VERIFICATION,
                SqlAccountRecoveryToken.id != token.id,
                SqlAccountRecoveryToken.consumed_at.is_(None),
                SqlAccountRecoveryToken.invalidated_at.is_(None),
            )
            .with_for_update()
        )
    )
    for item in remaining:
        item.invalidated_at = observed_at
    _cancel_token_mail(session, [item.id for item in remaining], observed_at)
    session.commit()


def request_password_reset(
    session: Session,
    *,
    email: str,
    public_origin: str,
    wrapper: KeyWrapper,
    now: datetime | None = None,
) -> None:
    observed_at = now or utc_now()
    try:
        normalized = normalize_recovery_email(email)
    except RecoveryInvalid:
        return
    state = session.scalar(
        select(SqlAccountEmail).where(SqlAccountEmail.verified_email == normalized)
    )
    if state is None:
        return
    _invalidate_tokens(session, state.account_id, AccountTokenPurpose.PASSWORD_RESET, observed_at)
    _issue_token_and_mail(
        session,
        account_id=state.account_id,
        email=normalized,
        purpose=AccountTokenPurpose.PASSWORD_RESET,
        public_origin=public_origin,
        wrapper=wrapper,
        now=observed_at,
    )
    session.commit()


def confirm_password_reset(
    session: Session,
    *,
    raw_token: str,
    password: str,
    now: datetime | None = None,
) -> None:
    observed_at = now or utc_now()
    try:
        digest = token_digest(raw_token)
        password_digest = hash_password(password)
    except (UnicodeEncodeError, ValueError) as error:
        raise RecoveryInvalid from error
    token = session.scalar(
        select(SqlAccountRecoveryToken)
        .where(SqlAccountRecoveryToken.token_digest == digest)
        .with_for_update()
    )
    if (
        token is None
        or token.purpose is not AccountTokenPurpose.PASSWORD_RESET
        or token.consumed_at is not None
        or token.invalidated_at is not None
        or _aware(token.expires_at) <= observed_at
    ):
        raise RecoveryInvalid
    account = session.get(SqlLocalAccount, token.account_id, with_for_update=True)
    if account is None:
        raise RecoveryInvalid
    account.password_digest = password_digest
    token.consumed_at = observed_at
    _cancel_token_mail(session, [token.id], observed_at)
    remaining = list(
        session.scalars(
            select(SqlAccountRecoveryToken)
            .where(
                SqlAccountRecoveryToken.account_id == account.id,
                SqlAccountRecoveryToken.purpose == AccountTokenPurpose.PASSWORD_RESET,
                SqlAccountRecoveryToken.id != token.id,
                SqlAccountRecoveryToken.consumed_at.is_(None),
                SqlAccountRecoveryToken.invalidated_at.is_(None),
            )
            .with_for_update()
        )
    )
    for item in remaining:
        item.invalidated_at = observed_at
    _cancel_token_mail(session, [item.id for item in remaining], observed_at)
    session.execute(
        update(SqlAuthSession)
        .where(SqlAuthSession.account_id == account.id, SqlAuthSession.revoked_at.is_(None))
        .values(revoked_at=observed_at)
    )
    session.commit()


def claim_mail(
    session: Session,
    *,
    worker_id: str,
    limit: int,
    lease_seconds: int,
    max_attempts: int,
    now: datetime | None = None,
) -> list[SqlMailOutbox]:
    if (
        not 1 <= len(worker_id) <= 100
        or not 1 <= limit <= 100
        or not 10 <= lease_seconds <= 300
        or not 1 <= max_attempts <= 100
    ):
        raise MailClaimInvalid
    observed_at = now or utc_now()
    candidates = list(
        session.scalars(
            select(SqlMailOutbox)
            .where(
                SqlMailOutbox.status.in_([MailOutboxStatus.PENDING, MailOutboxStatus.CLAIMED]),
                SqlMailOutbox.available_at <= observed_at,
            )
            .order_by(SqlMailOutbox.created_at, SqlMailOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    claimed: list[SqlMailOutbox] = []
    for row in candidates:
        if _aware(row.expires_at) <= observed_at:
            _clear_mail(row, MailOutboxStatus.EXPIRED, observed_at)
        elif row.attempts >= max_attempts:
            _clear_mail(row, MailOutboxStatus.DISCARDED, observed_at)
        else:
            row.status = MailOutboxStatus.CLAIMED
            row.attempts += 1
            row.claim_generation += 1
            row.claimed_by = worker_id
            row.claimed_at = observed_at
            row.available_at = observed_at + timedelta(seconds=lease_seconds)
            claimed.append(row)
    session.commit()
    return claimed


def decrypt_claimed_mail(row: SqlMailOutbox, wrapper: KeyWrapper) -> DecryptedMail:
    if (
        row.status is not MailOutboxStatus.CLAIMED
        or row.encrypted_payload is None
        or row.wrapped_data_key is None
        or row.encryption_key_version is None
        or row.payload_digest is None
    ):
        raise MailClaimInvalid
    plaintext = decrypt_credential(
        wrapper,
        context=_mail_context(row),
        encrypted=EncryptedCredential(
            row.encrypted_payload, row.wrapped_data_key, row.encryption_key_version
        ),
    )
    if not hmac.compare_digest(hashlib.sha256(plaintext.encode()).hexdigest(), row.payload_digest):
        raise MailClaimInvalid
    try:
        value = json.loads(plaintext)
        return DecryptedMail(
            recipient=str(value["recipient"]),
            action_url=str(value["action_url"]),
            template=str(value["template"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MailClaimInvalid from error


def finish_mail_claim(
    session: Session,
    *,
    mail_id: UUID,
    worker_id: str,
    claim_generation: int,
    delivered: bool,
    permanent_failure: bool = False,
    retry_after: timedelta = timedelta(seconds=30),
    max_attempts: int = 8,
    now: datetime | None = None,
) -> None:
    observed_at = now or utc_now()
    if not timedelta(0) <= retry_after <= timedelta(days=1) or not 1 <= max_attempts <= 100:
        raise MailClaimInvalid
    row = session.get(SqlMailOutbox, mail_id, with_for_update=True)
    if (
        row is None
        or row.status is not MailOutboxStatus.CLAIMED
        or row.claimed_by != worker_id
        or row.claim_generation != claim_generation
        or _aware(row.available_at) <= observed_at
    ):
        raise MailClaimInvalid
    if delivered:
        _clear_mail(row, MailOutboxStatus.DELIVERED, observed_at)
    elif permanent_failure or row.attempts >= max_attempts or _aware(row.expires_at) <= observed_at:
        _clear_mail(row, MailOutboxStatus.DISCARDED, observed_at)
    else:
        row.status = MailOutboxStatus.PENDING
        row.claimed_by = None
        row.claimed_at = None
        row.available_at = observed_at + retry_after
    session.commit()

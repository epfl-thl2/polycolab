"""SQLAlchemy entities owned by the accounts capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.enums import (
    AccountTokenPurpose,
    InvitationStatus,
    MailOutboxStatus,
    MailPurpose,
    SocialAuthPurpose,
    SocialIdentityAuditAction,
    SocialProviderKind,
)
from polycolab.entities.time import utc_now


class SqlUser(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    # Email is a mutable provider claim, not an identity key.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),)


class SqlLocalAccount(Base):
    """Development/self-hosted credentials; product authorization stays on User."""

    __tablename__ = "local_accounts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    # Social-only accounts deliberately have no password verifier. Password
    # authentication treats NULL and unknown encodings as ordinary failure.
    password_digest: Mapped[str | None] = mapped_column(String(300), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlAuthSession(Base):
    """Opaque database-backed browser session; only its digest is persisted."""

    __tablename__ = "auth_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reauthenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    password_reauthenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlRegistrationInvitation(Base):
    """Operator-issued built-in enrollment secret; raw codes are never persisted."""

    __tablename__ = "registration_invitations"
    __table_args__ = (
        Index("ix_registration_invitations_code_digest", "code_digest", unique=True),
        CheckConstraint("length(code_digest) = 64", name="ck_registration_invitation_digest"),
        CheckConstraint("expires_at > created_at", name="ck_registration_invitation_expiry"),
        CheckConstraint(
            "status IN ('PENDING', 'ACCEPTED', 'REVOKED')",
            name="ck_registration_invitation_status",
        ),
        CheckConstraint(
            "(status = 'PENDING' AND accepted_by_account_id IS NULL AND accepted_at IS NULL "
            "AND revoked_at IS NULL) OR (status = 'ACCEPTED' AND accepted_by_account_id IS NOT "
            "NULL AND accepted_at IS NOT NULL AND revoked_at IS NULL) OR (status = 'REVOKED' "
            "AND accepted_by_account_id IS NULL AND accepted_at IS NULL AND revoked_at IS NOT "
            "NULL)",
            name="ck_registration_invitation_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    code_digest: Mapped[str] = mapped_column(String(64))
    created_by_account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus, native_enum=False, length=16), default=InvitationStatus.PENDING
    )
    accepted_by_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_accounts.id"), nullable=True
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAccountEmail(Base):
    """Optional built-in recovery identity, distinct from provider email claims."""

    __tablename__ = "account_emails"
    __table_args__ = (
        CheckConstraint(
            "(verified_email IS NULL) = (verified_at IS NULL)",
            name="ck_account_email_verified_state",
        ),
        CheckConstraint(
            "(pending_email IS NULL) = (pending_requested_at IS NULL)",
            name="ck_account_email_pending_state",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), primary_key=True)
    verified_email: Mapped[str | None] = mapped_column(String(320), nullable=True, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pending_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    pending_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SqlAccountRecoveryToken(Base):
    """Single-use verification/reset capability; the raw token is never persisted."""

    __tablename__ = "account_recovery_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('EMAIL_VERIFICATION','PASSWORD_RESET')",
            name="ck_account_recovery_token_purpose",
        ),
        CheckConstraint("length(token_digest) = 64", name="ck_account_recovery_token_digest"),
        CheckConstraint("expires_at > created_at", name="ck_account_recovery_token_expiry"),
        CheckConstraint(
            "consumed_at IS NULL OR invalidated_at IS NULL",
            name="ck_account_recovery_token_terminal",
        ),
        Index(
            "ix_account_recovery_tokens_active",
            "account_id",
            "purpose",
            "expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    purpose: Mapped[AccountTokenPurpose] = mapped_column(
        Enum(AccountTokenPurpose, native_enum=False, length=32)
    )
    email: Mapped[str] = mapped_column(String(320))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlMailOutbox(Base):
    """Encrypted token-bearing mail with fenced, at-least-once delivery state."""

    __tablename__ = "mail_outbox"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('EMAIL_VERIFICATION','PASSWORD_RESET')",
            name="ck_mail_outbox_purpose",
        ),
        CheckConstraint(
            "status IN ('PENDING','CLAIMED','DELIVERED','CANCELLED','EXPIRED','DISCARDED')",
            name="ck_mail_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_mail_outbox_attempts"),
        CheckConstraint("claim_generation >= 0", name="ck_mail_outbox_claim_generation"),
        CheckConstraint("expires_at > created_at", name="ck_mail_outbox_expiry"),
        CheckConstraint(
            "(status IN ('PENDING','CLAIMED') AND encrypted_payload IS NOT NULL "
            "AND wrapped_data_key IS NOT NULL AND encryption_key_version IS NOT NULL "
            "AND payload_digest IS NOT NULL) OR "
            "(status IN ('DELIVERED','CANCELLED','EXPIRED','DISCARDED') "
            "AND encrypted_payload IS NULL AND wrapped_data_key IS NULL "
            "AND encryption_key_version IS NULL)",
            name="ck_mail_outbox_payload_lifecycle",
        ),
        Index("ix_mail_outbox_claim", "status", "available_at", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    token_id: Mapped[UUID] = mapped_column(ForeignKey("account_recovery_tokens.id"), unique=True)
    purpose: Mapped[MailPurpose] = mapped_column(Enum(MailPurpose, native_enum=False, length=32))
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    wrapped_data_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_key_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[MailOutboxStatus] = mapped_column(
        Enum(MailOutboxStatus, native_enum=False, length=16), default=MailOutboxStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_generation: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAccountRecoveryRateWindow(Base):
    """Durable HMAC-scoped abuse counter; no raw address or email is retained."""

    __tablename__ = "account_recovery_rate_windows"
    __table_args__ = (
        UniqueConstraint(
            "action", "scope_digest", "window_started_at", name="uq_account_recovery_rate_window"
        ),
        CheckConstraint(
            "action IN ('EMAIL_CHANGE','EMAIL_RESEND','PASSWORD_RESET')",
            name="ck_account_recovery_rate_action",
        ),
        CheckConstraint("length(scope_digest) = 64", name="ck_account_recovery_rate_digest"),
        CheckConstraint("count >= 0", name="ck_account_recovery_rate_count"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    action: Mapped[str] = mapped_column(String(32))
    scope_digest: Mapped[str] = mapped_column(String(64), index=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class SqlSocialAccountIdentity(Base):
    """Stable provider identity permanently bound to one built-in account."""

    __tablename__ = "social_account_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_social_identity_provider_subject"),
        UniqueConstraint("account_id", "provider", name="uq_social_identity_account_provider"),
        CheckConstraint("provider IN ('google', 'github')", name="ck_social_identity_provider"),
        CheckConstraint(
            "length(subject) BETWEEN 1 AND 255", name="ck_social_identity_subject_length"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    provider: Mapped[SocialProviderKind] = mapped_column(
        Enum(
            SocialProviderKind,
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        )
    )
    subject: Mapped[str] = mapped_column(String(255))
    unlinked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlSocialAuthTransaction(Base):
    """Short-lived cross-replica OAuth state; raw flow values never leave auth code."""

    __tablename__ = "social_auth_transactions"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('google', 'github')", name="ck_social_auth_transaction_provider"
        ),
        CheckConstraint(
            "purpose IN ('SIGN_IN', 'LINK')", name="ck_social_auth_transaction_purpose"
        ),
        CheckConstraint(
            "length(state_digest) = 64 AND length(browser_binding_digest) = 64",
            name="ck_social_auth_transaction_digest_length",
        ),
        CheckConstraint(
            "length(pkce_verifier) BETWEEN 43 AND 128 AND length(nonce) BETWEEN 32 AND 128",
            name="ck_social_auth_transaction_secret_length",
        ),
        CheckConstraint(
            "length(return_path) BETWEEN 1 AND 500",
            name="ck_social_auth_transaction_return_path_length",
        ),
        CheckConstraint("expires_at > created_at", name="ck_social_auth_transaction_expiry"),
        CheckConstraint(
            "(purpose = 'SIGN_IN' AND linked_account_id IS NULL AND linked_session_id IS NULL) "
            "OR (purpose = 'LINK' AND linked_account_id IS NOT NULL "
            "AND linked_session_id IS NOT NULL)",
            name="ck_social_auth_transaction_link_binding",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    browser_binding_digest: Mapped[str] = mapped_column(String(64))
    provider: Mapped[SocialProviderKind] = mapped_column(
        Enum(
            SocialProviderKind,
            native_enum=False,
            length=16,
            values_callable=lambda values: [value.value for value in values],
        )
    )
    purpose: Mapped[SocialAuthPurpose] = mapped_column(
        Enum(SocialAuthPurpose, native_enum=False, length=16)
    )
    pkce_verifier: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(128))
    return_path: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    linked_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_accounts.id"), nullable=True
    )
    linked_session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("auth_sessions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlSocialIdentityAudit(Base):
    """Immutable creation/link lifecycle evidence without provider flow secrets."""

    __tablename__ = "social_identity_audits"
    __table_args__ = (
        CheckConstraint(
            "action IN ('CREATED', 'LINKED', 'UNLINKED', 'RELINKED')",
            name="ck_social_identity_audit_action",
        ),
        CheckConstraint(
            "(action = 'CREATED' AND actor_account_id IS NULL) "
            "OR (action <> 'CREATED' AND actor_account_id IS NOT NULL)",
            name="ck_social_identity_audit_actor",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("social_account_identities.id"), index=True
    )
    account_id: Mapped[UUID] = mapped_column(ForeignKey("local_accounts.id"), index=True)
    actor_account_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("local_accounts.id"), nullable=True
    )
    action: Mapped[SocialIdentityAuditAction] = mapped_column(
        Enum(SocialIdentityAuditAction, native_enum=False, length=16)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


__all__ = [
    "SqlUser",
    "SqlLocalAccount",
    "SqlAuthSession",
    "SqlRegistrationInvitation",
    "SqlAccountEmail",
    "SqlAccountRecoveryToken",
    "SqlMailOutbox",
    "SqlAccountRecoveryRateWindow",
    "SqlSocialAccountIdentity",
    "SqlSocialAuthTransaction",
    "SqlSocialIdentityAudit",
]

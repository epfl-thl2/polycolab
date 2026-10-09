"""SQLAlchemy entities owned by the model_gateway capability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlGatewayProfile(Base):
    """User-owned OpenAI-compatible routing metadata and encrypted secret only."""

    __tablename__ = "gateway_profiles"
    __table_args__ = (
        CheckConstraint(
            "wire_api IN ('responses', 'chat_completions')", name="ck_gateway_wire_api"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(2048))
    model_id: Mapped[str] = mapped_column(String(500))
    wire_api: Mapped[str] = mapped_column(String(32), default="responses")
    credential_version: Mapped[int] = mapped_column(Integer, default=1)
    encrypted_credential: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary)
    encryption_key_version: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlGatewayCredentialRewrapAudit(Base):
    """Private immutable record of an exact credential-envelope CAS migration."""

    __tablename__ = "gateway_credential_rewrap_audit"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "credential_version",
            "target_key_version",
            name="uq_gateway_credential_rewrap_target",
        ),
        CheckConstraint(
            "length(source_fingerprint) = 64",
            name="ck_gateway_credential_rewrap_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("gateway_profiles.id"), index=True)
    credential_version: Mapped[int] = mapped_column(Integer)
    source_key_version: Mapped[str] = mapped_column(String(200))
    target_key_version: Mapped[str] = mapped_column(String(200))
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlGatewayRunGrant(Base):
    """Opaque, one-use internal claim token; never a provider credential."""

    __tablename__ = "gateway_run_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("gateway_profiles.id"), index=True)
    run_id: Mapped[UUID] = mapped_column(index=True)
    model_id: Mapped[str] = mapped_column(String(500))
    credential_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


__all__ = [
    "SqlGatewayProfile",
    "SqlGatewayCredentialRewrapAudit",
    "SqlGatewayRunGrant",
]


class SqlHostedModelRequest(Base):
    """One API-owned dispatch and billing record; never stores prompts or responses."""

    __tablename__ = "hosted_model_requests"
    __table_args__ = (
        UniqueConstraint("run_id", "request_key", name="uq_hosted_model_request_key"),
        CheckConstraint(
            "state IN ('PENDING','COMPLETED','UNCERTAIN')", name="ck_hosted_request_state"
        ),
        CheckConstraint(
            "generation >= 1 AND input_tokens >= 0 AND output_tokens >= 0 AND cost_microusd >= 0",
            name="ck_hosted_request_usage",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(200))
    request_digest: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="PENDING")
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_microusd: Mapped[int] = mapped_column(Integer)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    settle_by: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

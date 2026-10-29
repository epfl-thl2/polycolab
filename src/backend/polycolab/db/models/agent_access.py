"""External agent identities and credentials."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from polycolab.db.base import Base
from polycolab.entities.time import utc_now


class SqlExternalAgentIdentity(Base):
    __tablename__ = "external_agent_identities"
    __table_args__ = (
        UniqueConstraint("id", "sponsor_user_id", name="uq_external_identity_sponsor"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlExternalAgentCredential(Base):
    """Opaque delegated identity; historical project grants remain immutable."""

    __tablename__ = "external_agent_credentials"
    __table_args__ = (
        UniqueConstraint(
            "id", "project_id", "sponsor_user_id", name="uq_external_agent_credential_identity"
        ),
        UniqueConstraint("id", "sponsor_user_id", name="uq_external_credential_sponsor"),
        UniqueConstraint("id", "agent_id", "sponsor_user_id", name="uq_external_credential_agent"),
        ForeignKeyConstraint(
            ["agent_id", "sponsor_user_id"],
            ["external_agent_identities.id", "external_agent_identities.sponsor_user_id"],
            name="fk_credential_agent_sponsor",
        ),
        CheckConstraint(
            "(scope_kind = 'ACCOUNT' AND project_id IS NULL) OR "
            "(scope_kind = 'PROJECT' AND project_id IS NOT NULL)",
            name="ck_external_credential_scope",
        ),
        CheckConstraint("length(token_digest) = 64", name="ck_external_agent_token_digest"),
        CheckConstraint("request_count >= 0", name="ck_external_agent_request_count"),
        CheckConstraint("mutation_count >= 0", name="ck_external_agent_mutation_count"),
        CheckConstraint("max_requests > 0", name="ck_external_agent_max_requests"),
        CheckConstraint("max_mutations > 0", name="ck_external_agent_max_mutations"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    scope_kind: Mapped[str] = mapped_column(String(16), default="ACCOUNT")
    sponsor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("external_agent_identities.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    encrypted_secret: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    wrapped_data_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encryption_key_version: Mapped[str | None] = mapped_column(String(200), nullable=True)

    @property
    def secret_reveal_available(self) -> bool:
        return self.revoked_at is None and all(
            (self.encrypted_secret, self.wrapped_data_key, self.encryption_key_version)
        )

    fixed_rights: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    mutation_count: Mapped[int] = mapped_column(Integer, default=0)
    max_requests: Mapped[int] = mapped_column(Integer)
    max_mutations: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

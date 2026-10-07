"""Application account identity, without credentials or ORM state."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from polycolab.entities.enums import InvitationStatus


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemberAccount:
    """Information needed to resolve a workspace invitation by username."""

    id: UUID
    username: str
    display_name: str | None


class IdentifiedUser(Protocol):
    """Minimal identity required by application mutations."""

    @property
    def id(self) -> UUID: ...

    @property
    def email(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class Principal:
    issuer: str
    subject: str
    email: str | None = None
    display_name: str | None = None


@dataclass(frozen=True, slots=True)
class LocalAccount:
    id: UUID
    username: str
    password_digest: str | None = field(repr=False)
    display_name: str | None
    is_admin: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthSession:
    id: UUID
    account_id: UUID
    expires_at: datetime
    revoked_at: datetime | None
    reauthenticated_at: datetime
    password_reauthenticated_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RegistrationInvitation:
    id: UUID
    created_by_account_id: UUID
    expires_at: datetime
    status: InvitationStatus
    accepted_by_account_id: UUID | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IssuedRegistrationInvitation:
    invitation: RegistrationInvitation
    code: str = field(repr=False)

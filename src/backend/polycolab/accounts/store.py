"""Persistence operations needed by application identity synchronization."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from polycolab.entities.accounts import (
    AuthSession,
    LocalAccount,
    MemberAccount,
    RegistrationInvitation,
    User,
)


class AccountStore(Protocol):
    def user(self, user_id: UUID) -> User | None: ...

    def user_by_subject(self, issuer: str, subject: str) -> User | None: ...

    def user_by_username(self, username: str) -> User | None: ...

    def set_username(self, user_id: UUID, username: str) -> User | None: ...

    def member_account(self, username: str) -> MemberAccount | None: ...

    def create_user(
        self, *, issuer: str, subject: str, email: str | None, display_name: str | None
    ) -> User: ...

    def update_display_claims(
        self, user_id: UUID, *, email: str | None, display_name: str | None
    ) -> User: ...

    def lock_registry(self) -> None: ...

    def account_count(self) -> int: ...

    def local_account(self, account_id: UUID) -> LocalAccount | None: ...

    def local_account_by_username(self, username: str) -> LocalAccount | None: ...

    def create_local_account(
        self,
        *,
        username: str,
        password_digest: str,
        display_name: str | None,
        is_admin: bool,
        at: datetime | None = None,
    ) -> LocalAccount: ...

    def create_session(
        self,
        *,
        account_id: UUID,
        digest: str,
        created_at: datetime,
        expires_at: datetime,
        password_authenticated: bool,
    ) -> None: ...

    def auth_session(
        self,
        digest: str,
        *,
        active_at: datetime | None,
        lock: bool = False,
    ) -> AuthSession | None: ...

    def reauthenticate_session(self, session_id: UUID, *, at: datetime) -> None: ...

    def revoke_session(self, session_id: UUID, *, at: datetime) -> None: ...

    def delete_expired_sessions(self, *, at: datetime) -> None: ...

    def create_registration_invitation(
        self,
        *,
        digest: str,
        created_by: UUID,
        created_at: datetime,
        expires_at: datetime,
    ) -> RegistrationInvitation: ...

    def registration_invitations(self, *, limit: int) -> tuple[RegistrationInvitation, ...]: ...

    def registration_invitation(self, invitation_id: UUID) -> RegistrationInvitation | None: ...

    def registration_invitation_by_digest(self, digest: str) -> RegistrationInvitation | None: ...

    def revoke_registration_invitation(self, invitation_id: UUID, *, at: datetime) -> None: ...

    def accept_registration_invitation(
        self,
        invitation_id: UUID,
        *,
        account_id: UUID,
        at: datetime,
    ) -> None: ...

"""SQL persistence for application user identity synchronization."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from polycolab.db.converters import accounts as converter
from polycolab.db.converters.accounts import user
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import SqlAuthSession, SqlLocalAccount, SqlRegistrationInvitation, SqlUser
from polycolab.entities import accounts as entities
from polycolab.entities.accounts import MemberAccount, User
from polycolab.entities.enums import InvitationStatus


class SqlAccountStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    @persistence_boundary
    def user(self, user_id: UUID) -> User | None:
        row = self._session.get(SqlUser, user_id)
        return user(row) if row is not None else None

    @persistence_boundary
    def user_by_subject(self, issuer: str, subject: str) -> User | None:
        row = self._session.scalar(
            select(SqlUser).where(SqlUser.issuer == issuer, SqlUser.subject == subject)
        )
        return user(row) if row is not None else None

    @persistence_boundary
    def member_account(self, username: str) -> MemberAccount | None:
        row = self._session.scalar(
            select(SqlLocalAccount).where(SqlLocalAccount.username == username)
        )
        return MemberAccount(row.id, row.username, row.display_name) if row is not None else None

    @persistence_boundary
    def create_user(
        self, *, issuer: str, subject: str, email: str | None, display_name: str | None
    ) -> User:
        row = SqlUser(issuer=issuer, subject=subject, email=email, display_name=display_name)
        self._session.add(row)
        self._session.flush()
        return user(row)

    @persistence_boundary
    def update_display_claims(
        self, user_id: UUID, *, email: str | None, display_name: str | None
    ) -> User:
        row = self._session.get(SqlUser, user_id)
        if row is None:
            raise LookupError("user disappeared during identity synchronization")
        if email is not None:
            row.email = email
        row.display_name = display_name
        self._session.flush()
        return user(row)

    @persistence_boundary
    def lock_registry(self) -> None:
        if self._session.get_bind().dialect.name == "postgresql":
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": 7_418_311_903}
            )

    @persistence_boundary
    def account_count(self) -> int:
        return int(self._session.scalar(select(func.count()).select_from(SqlLocalAccount)) or 0)

    @persistence_boundary
    def local_account(self, account_id: UUID) -> entities.LocalAccount | None:
        row = self._session.get(SqlLocalAccount, account_id)
        return converter.local_account(row) if row is not None else None

    @persistence_boundary
    def local_account_by_username(self, username: str) -> entities.LocalAccount | None:
        row = self._session.scalar(
            select(SqlLocalAccount).where(SqlLocalAccount.username == username)
        )
        return converter.local_account(row) if row is not None else None

    @persistence_boundary
    def create_local_account(
        self,
        *,
        username: str,
        password_digest: str,
        display_name: str | None,
        is_admin: bool,
        at: datetime | None = None,
    ) -> entities.LocalAccount:
        row = SqlLocalAccount(
            username=username,
            password_digest=password_digest,
            display_name=display_name,
            is_admin=is_admin,
        )
        if at is not None:
            row.created_at = at
            row.updated_at = at
        self._session.add(row)
        self._session.flush()
        return converter.local_account(row)

    @persistence_boundary
    def create_session(
        self,
        *,
        account_id: UUID,
        digest: str,
        created_at: datetime,
        expires_at: datetime,
        password_authenticated: bool,
    ) -> None:
        self._session.add(
            SqlAuthSession(
                account_id=account_id,
                token_digest=digest,
                expires_at=expires_at,
                reauthenticated_at=created_at,
                password_reauthenticated_at=created_at if password_authenticated else None,
                created_at=created_at,
            )
        )
        self._session.flush()

    @persistence_boundary
    def auth_session(
        self,
        digest: str,
        *,
        active_at: datetime | None,
        lock: bool = False,
    ) -> entities.AuthSession | None:
        statement = select(SqlAuthSession).where(SqlAuthSession.token_digest == digest)
        if active_at is not None:
            statement = statement.where(
                SqlAuthSession.revoked_at.is_(None), SqlAuthSession.expires_at > active_at
            )
        if lock:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        return converter.auth_session(row) if row is not None else None

    @persistence_boundary
    def reauthenticate_session(self, session_id: UUID, *, at: datetime) -> None:
        row = self._session.get(SqlAuthSession, session_id)
        if row is None:
            raise LookupError("session disappeared during reauthentication")
        row.reauthenticated_at = at
        row.password_reauthenticated_at = at
        self._session.flush()

    @persistence_boundary
    def revoke_session(self, session_id: UUID, *, at: datetime) -> None:
        row = self._session.get(SqlAuthSession, session_id)
        if row is None:
            raise LookupError("session disappeared during revocation")
        row.revoked_at = at
        self._session.flush()

    @persistence_boundary
    def delete_expired_sessions(self, *, at: datetime) -> None:
        self._session.query(SqlAuthSession).filter(
            (SqlAuthSession.expires_at <= at) | SqlAuthSession.revoked_at.is_not(None)
        ).delete(synchronize_session=False)

    @persistence_boundary
    def create_registration_invitation(
        self,
        *,
        digest: str,
        created_by: UUID,
        created_at: datetime,
        expires_at: datetime,
    ) -> entities.RegistrationInvitation:
        row = SqlRegistrationInvitation(
            code_digest=digest,
            created_by_account_id=created_by,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return converter.registration_invitation(row)

    @persistence_boundary
    def registration_invitations(
        self, *, limit: int
    ) -> tuple[entities.RegistrationInvitation, ...]:
        return tuple(
            converter.registration_invitation(row)
            for row in self._session.scalars(
                select(SqlRegistrationInvitation)
                .order_by(
                    SqlRegistrationInvitation.created_at.desc(), SqlRegistrationInvitation.id.desc()
                )
                .limit(limit)
            )
        )

    @persistence_boundary
    def registration_invitation(
        self, invitation_id: UUID
    ) -> entities.RegistrationInvitation | None:
        row = self._session.scalar(
            select(SqlRegistrationInvitation)
            .where(SqlRegistrationInvitation.id == invitation_id)
            .with_for_update()
        )
        return converter.registration_invitation(row) if row is not None else None

    @persistence_boundary
    def registration_invitation_by_digest(
        self, digest: str
    ) -> entities.RegistrationInvitation | None:
        row = self._session.scalar(
            select(SqlRegistrationInvitation)
            .where(SqlRegistrationInvitation.code_digest == digest)
            .with_for_update()
        )
        return converter.registration_invitation(row) if row is not None else None

    @persistence_boundary
    def revoke_registration_invitation(self, invitation_id: UUID, *, at: datetime) -> None:
        row = self._session.get(SqlRegistrationInvitation, invitation_id)
        if row is None:
            raise LookupError("registration invitation disappeared during revocation")
        row.status = InvitationStatus.REVOKED
        row.revoked_at = at
        self._session.flush()

    @persistence_boundary
    def accept_registration_invitation(
        self,
        invitation_id: UUID,
        *,
        account_id: UUID,
        at: datetime,
    ) -> None:
        row = self._session.get(SqlRegistrationInvitation, invitation_id)
        if row is None:
            raise LookupError("registration invitation disappeared during acceptance")
        row.status = InvitationStatus.ACCEPTED
        row.accepted_by_account_id = account_id
        row.accepted_at = at
        self._session.flush()

"""Materialize account identity without leaking credentials or session state."""

from polycolab.db.converters.time import timestamp
from polycolab.db.models import accounts as rows
from polycolab.db.models.accounts import SqlUser
from polycolab.entities import accounts as entities
from polycolab.entities.accounts import User


def user(row: SqlUser) -> User:
    return User(
        id=row.id,
        issuer=row.issuer,
        subject=row.subject,
        email=row.email,
        display_name=row.display_name,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
        username=row.username,
    )


def local_account(row: rows.SqlLocalAccount) -> entities.LocalAccount:
    return entities.LocalAccount(
        id=row.id,
        username=row.username,
        password_digest=row.password_digest,
        display_name=row.display_name,
        is_admin=row.is_admin,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
    )


def auth_session(row: rows.SqlAuthSession) -> entities.AuthSession:
    return entities.AuthSession(
        id=row.id,
        account_id=row.account_id,
        expires_at=timestamp(row.expires_at),
        revoked_at=timestamp(row.revoked_at),
        reauthenticated_at=timestamp(row.reauthenticated_at),
        password_reauthenticated_at=timestamp(row.password_reauthenticated_at),
        created_at=timestamp(row.created_at),
    )


def registration_invitation(row: rows.SqlRegistrationInvitation) -> entities.RegistrationInvitation:
    return entities.RegistrationInvitation(
        id=row.id,
        created_by_account_id=row.created_by_account_id,
        expires_at=timestamp(row.expires_at),
        status=row.status,
        accepted_by_account_id=row.accepted_by_account_id,
        accepted_at=timestamp(row.accepted_at),
        revoked_at=timestamp(row.revoked_at),
        created_at=timestamp(row.created_at),
    )

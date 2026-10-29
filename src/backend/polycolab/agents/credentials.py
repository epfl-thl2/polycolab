"""Credential validation and finite request and mutation budgets."""

import hashlib
import hmac
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from polycolab.db.models.agent_access import SqlExternalAgentCredential
from polycolab.entities.access import ActorOperation
from polycolab.entities.time import utc_now

FIXED_RIGHTS = frozenset({ActorOperation.PROJECT_WRITE})


class ExternalAgentInvalid(Exception):
    pass


class ExternalAgentConflict(Exception):
    pass


class ExternalAgentLimit(Exception):
    pass


class ExternalAgentUploadInterrupted(Exception):
    pass


def fixed_right_values() -> list[str]:
    return sorted(right.value for right in FIXED_RIGHTS)


def credential_rights(credential: SqlExternalAgentCredential) -> frozenset[ActorOperation]:
    try:
        values = credential.fixed_rights
        rights = frozenset(ActorOperation(value) for value in values)
    except TypeError, ValueError:
        raise ExternalAgentInvalid from None
    if len(values) != len(rights) or rights != FIXED_RIGHTS:
        raise ExternalAgentInvalid
    return rights


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def credential_from_secret(
    session: Session, secret: str, *, consume_request: bool = True, allow_project: bool = False
) -> SqlExternalAgentCredential:
    parts = secret.split("_", maxsplit=2)
    if len(parts) != 3 or parts[0] != "pca":
        raise ExternalAgentInvalid
    try:
        credential_id = UUID(hex=parts[1])
    except ValueError:
        raise ExternalAgentInvalid from None
    # Atomic admission also works with SQLite, whose SELECT FOR UPDATE is a no-op.
    if consume_request:
        admitted = session.scalar(
            update(SqlExternalAgentCredential)
            .where(
                SqlExternalAgentCredential.id == credential_id,
                SqlExternalAgentCredential.token_digest == _digest(secret),
                SqlExternalAgentCredential.revoked_at.is_(None),
                SqlExternalAgentCredential.expires_at > utc_now(),
                SqlExternalAgentCredential.request_count < SqlExternalAgentCredential.max_requests,
                SqlExternalAgentCredential.scope_kind.in_(
                    ["ACCOUNT", "PROJECT"] if allow_project else ["ACCOUNT"]
                ),
            )
            .values(request_count=SqlExternalAgentCredential.request_count + 1)
            .returning(SqlExternalAgentCredential)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
        if admitted is not None:
            credential_rights(admitted)
            session.commit()
            return admitted
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        credential is None
        or credential.revoked_at is not None
        or _aware(credential.expires_at) <= utc_now()
        or not hmac.compare_digest(credential.token_digest, _digest(secret))
        or (credential.scope_kind == "PROJECT" and not allow_project)
    ):
        raise ExternalAgentInvalid
    credential_rights(credential)
    if consume_request:
        raise ExternalAgentLimit("credential_request_budget_exhausted")
    return credential


def reserve_file_mutation(session: Session, secret: str) -> None:
    """Reserve before filesystem I/O without a read-to-write transaction upgrade."""
    credential = session.scalar(
        update(SqlExternalAgentCredential)
        .where(
            SqlExternalAgentCredential.token_digest == _digest(secret),
            SqlExternalAgentCredential.revoked_at.is_(None),
            SqlExternalAgentCredential.expires_at > utc_now(),
            SqlExternalAgentCredential.mutation_count < SqlExternalAgentCredential.max_mutations,
        )
        .values(mutation_count=SqlExternalAgentCredential.mutation_count + 1)
        .returning(SqlExternalAgentCredential)
        .execution_options(populate_existing=True, synchronize_session=False)
    )
    if credential is None:
        credential_from_secret(session, secret, consume_request=False, allow_project=True)
        raise ExternalAgentLimit("credential_mutation_budget_exhausted")
    credential_rights(credential)
    session.commit()


def consume_mutation(session: Session, *, credential_id: UUID) -> None:
    """Consume one finite mutation only after an idempotency check created work."""

    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(SqlExternalAgentCredential.id == credential_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if credential is None:
        raise ExternalAgentInvalid
    if credential.mutation_count >= credential.max_mutations:
        raise ExternalAgentLimit("credential_mutation_budget_exhausted")
    credential.mutation_count += 1

"""Human-owned external agent credential management."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectNotFound,
)
from polycolab.agents.credentials import (
    FIXED_RIGHTS as FIXED_RIGHTS,
)
from polycolab.agents.credentials import (
    ExternalAgentConflict as ExternalAgentConflict,
)
from polycolab.agents.credentials import (
    ExternalAgentInvalid as ExternalAgentInvalid,
)
from polycolab.agents.credentials import (
    ExternalAgentLimit as ExternalAgentLimit,
)
from polycolab.agents.credentials import (
    ExternalAgentUploadInterrupted as ExternalAgentUploadInterrupted,
)
from polycolab.agents.credentials import (
    _aware as _aware,
)
from polycolab.agents.credentials import (
    _digest as _digest,
)
from polycolab.agents.credentials import (
    consume_mutation as consume_mutation,
)
from polycolab.agents.credentials import (
    credential_from_secret as credential_from_secret,
)
from polycolab.agents.credentials import (
    credential_rights as credential_rights,
)
from polycolab.agents.credentials import (
    fixed_right_values as fixed_right_values,
)
from polycolab.db.models import (
    SqlExternalAgentCredential,
)
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    EncryptedCredential,
    KeyWrapper,
    decrypt_credential,
    encrypt_credential,
)


@dataclass(frozen=True, slots=True)
class IssuedCredential:
    credential: SqlExternalAgentCredential
    secret: str


def issue_credential(
    session: Session,
    *,
    sponsor: IdentifiedUser,
    name: str,
    ttl_seconds: int,
    max_requests: int,
    max_mutations: int,
    agent_id: UUID | None = None,
    wrapper: KeyWrapper | None = None,
) -> IssuedCredential:
    from polycolab.db.models import SqlExternalAgentIdentity

    if agent_id is None:
        identity = SqlExternalAgentIdentity(sponsor_user_id=sponsor.id, name=name)
        session.add(identity)
        session.flush()
        agent_id = identity.id
    else:
        existing_identity = session.get(SqlExternalAgentIdentity, agent_id)
        if existing_identity is None or existing_identity.sponsor_user_id != sponsor.id:
            raise AuthorizationDenied("agent identity is not owned by this account")
    credential_id = uuid4()
    secret = f"pca_{credential_id.hex}_{secrets.token_urlsafe(32)}"
    credential = SqlExternalAgentCredential(
        id=credential_id,
        project_id=None,
        scope_kind="ACCOUNT",
        agent_id=agent_id,
        sponsor_user_id=sponsor.id,
        name=name,
        token_digest=_digest(secret),
        fixed_rights=fixed_right_values(),
        expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        max_requests=max_requests,
        max_mutations=max_mutations,
    )
    if wrapper is not None:
        encrypted = encrypt_credential(
            wrapper, context=key_secret_context(sponsor.id, credential_id), secret=secret
        )
        credential.encrypted_secret = encrypted.ciphertext
        credential.wrapped_data_key = encrypted.wrapped_key
        credential.encryption_key_version = encrypted.key_version
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return IssuedCredential(credential, secret)


def key_secret_context(user_id: UUID, credential_id: UUID) -> bytes:
    return f"polycolab:agent-key:{user_id}:{credential_id}".encode("ascii")


def reveal_credential(
    session: Session, *, credential_id: UUID, user_id: UUID, wrapper: KeyWrapper
) -> str:
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(
            SqlExternalAgentCredential.id == credential_id,
            SqlExternalAgentCredential.sponsor_user_id == user_id,
        )
        .with_for_update()
    )
    if credential is None:
        raise ProjectNotFound
    if (
        credential.revoked_at is not None
        or not credential.encrypted_secret
        or not credential.wrapped_data_key
        or not credential.encryption_key_version
    ):
        raise ExternalAgentConflict
    return decrypt_credential(
        wrapper,
        context=key_secret_context(user_id, credential_id),
        encrypted=EncryptedCredential(
            credential.encrypted_secret,
            credential.wrapped_data_key,
            credential.encryption_key_version,
        ),
    )


def revoke_credential(
    session: Session, *, credential_id: UUID, user_id: UUID
) -> SqlExternalAgentCredential:
    credential = session.scalar(
        select(SqlExternalAgentCredential)
        .where(
            SqlExternalAgentCredential.id == credential_id,
            SqlExternalAgentCredential.sponsor_user_id == user_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if credential is None:
        raise ProjectNotFound
    if credential.revoked_at is None:
        credential.revoked_at = utc_now()
        session.commit()
    return credential

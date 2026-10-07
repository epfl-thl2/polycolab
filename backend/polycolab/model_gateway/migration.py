"""Version-routed credential reads and non-destructive rewrap preparation.

No database mutation or migration CLI. Integration must compare the original
envelope under a short transaction and append audit/checkpoint records atomically.
All key-service I/O takes place before that transaction.
"""

import base64
import hashlib
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlGatewayCredentialRewrapAudit, SqlGatewayProfile
from polycolab.model_gateway.credentials import (
    CredentialError,
    EncryptedCredential,
    KeyWrapper,
    decrypt_credential,
)


class CredentialMigrationConflict(Exception):
    """The exact source envelope or its current owner binding changed."""


@dataclass(frozen=True)
class CredentialEnvelopeSnapshot:
    profile_id: UUID
    user_id: UUID
    credential_version: int
    encrypted: EncryptedCredential = field(repr=False)


def envelope_fingerprint(value: EncryptedCredential) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                value.key_version,
                base64.b64encode(value.ciphertext).decode(),
                base64.b64encode(value.wrapped_key).decode(),
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class RewrapCandidate:
    expected_fingerprint: str
    encrypted: EncryptedCredential = field(repr=False)


class CredentialKeyring:
    """Exact operator-registered version routing; no trial decryption/fallback.

    Register legacy AwsKmsKeyWrapper instances under their existing stored version
    strings. Keep those readers until migration and restore evidence are complete.
    """

    def __init__(
        self, wrappers: Sequence[KeyWrapper], *, active_version: str | None = None
    ) -> None:
        by_version = {wrapper.key_version: wrapper for wrapper in wrappers}
        if (
            not wrappers
            or len(by_version) != len(wrappers)
            or any(not version for version in by_version)
        ):
            raise ValueError("unique explicit envelope versions required")
        self._wrappers = MappingProxyType(by_version)
        self._active_version = active_version or wrappers[-1].key_version
        if self._active_version not in by_version:
            raise ValueError("active envelope version must be registered")

    @property
    def key_version(self) -> str:
        return self._active_version

    def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
        return self.wrapper(self._active_version).wrap(plaintext_key, context)

    def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
        return self.wrapper(self._active_version).unwrap(wrapped_key, context)

    def close(self) -> None:
        for wrapper in self._wrappers.values():
            close = getattr(wrapper, "close", None)
            if close is not None:
                close()

    def wrapper(self, version: str) -> KeyWrapper:
        try:
            return self._wrappers[version]
        except KeyError:
            raise CredentialError("credential_key_version_unavailable") from None

    def decrypt(self, *, context: bytes, encrypted: EncryptedCredential) -> str:
        return decrypt_credential(
            self.wrapper(encrypted.key_version), context=context, encrypted=encrypted
        )

    def prepare_rewrap(
        self, *, context: bytes, encrypted: EncryptedCredential, target_version: str
    ) -> RewrapCandidate:
        source = self.wrapper(encrypted.key_version)
        target = self.wrapper(target_version)
        data_key = source.unwrap(encrypted.wrapped_key, context)
        try:
            if len(data_key) != 32:
                raise ValueError
            # Verify the original envelope before preparing a replacement.
            AESGCM(data_key).decrypt(encrypted.ciphertext[:12], encrypted.ciphertext[12:], context)
        except Exception:
            raise CredentialError("credential_decryption_failed") from None
        if source.key_version == target.key_version:
            return RewrapCandidate(envelope_fingerprint(encrypted), encrypted)
        wrapped = target.wrap(data_key, context)
        # Confirm the new wrapping is usable before offering it for persistence.
        if not hmac.compare_digest(target.unwrap(wrapped, context), data_key):
            raise CredentialError("credential_rewrap_verification_failed")
        candidate = EncryptedCredential(encrypted.ciphertext, wrapped, target.key_version)
        return RewrapCandidate(envelope_fingerprint(encrypted), candidate)


def rewrap_snapshot_page(
    session: Session,
    *,
    target_version: str,
    after: UUID | None = None,
    limit: int = 100,
) -> list[CredentialEnvelopeSnapshot]:
    """Read one bounded page without locks or key-service I/O.

    The operator must end this read transaction before preparing candidates.
    """

    if not 1 <= limit <= 100:
        raise ValueError("credential migration page limit must be between 1 and 100")
    statement = (
        select(SqlGatewayProfile)
        .where(
            SqlGatewayProfile.deleted_at.is_(None),
            SqlGatewayProfile.encryption_key_version != target_version,
        )
        .order_by(SqlGatewayProfile.id)
        .limit(limit)
    )
    if after is not None:
        statement = statement.where(SqlGatewayProfile.id > after)
    return [
        CredentialEnvelopeSnapshot(
            profile_id=profile.id,
            user_id=profile.user_id,
            credential_version=profile.credential_version,
            encrypted=EncryptedCredential(
                profile.encrypted_credential,
                profile.wrapped_data_key,
                profile.encryption_key_version,
            ),
        )
        for profile in session.scalars(statement)
    ]


def commit_rewrap_candidate(
    session: Session,
    *,
    snapshot: CredentialEnvelopeSnapshot,
    candidate: RewrapCandidate,
) -> SqlGatewayCredentialRewrapAudit:
    """Atomically compare, replace and audit an already-verified candidate."""

    if candidate.encrypted.ciphertext != snapshot.encrypted.ciphertext:
        raise ValueError("rewrap must preserve the encrypted provider credential")
    if not hmac.compare_digest(
        candidate.expected_fingerprint, envelope_fingerprint(snapshot.encrypted)
    ):
        raise ValueError("rewrap candidate does not match its source snapshot")
    if candidate.encrypted.key_version == snapshot.encrypted.key_version:
        raise ValueError("rewrap target must differ from the source version")
    try:
        profile = session.scalar(
            select(SqlGatewayProfile)
            .where(SqlGatewayProfile.id == snapshot.profile_id)
            .with_for_update()
        )
        if profile is None or profile.deleted_at is not None or profile.user_id != snapshot.user_id:
            raise CredentialMigrationConflict("credential_owner_binding_changed")
        current = EncryptedCredential(
            profile.encrypted_credential,
            profile.wrapped_data_key,
            profile.encryption_key_version,
        )
        if profile.credential_version != snapshot.credential_version or not hmac.compare_digest(
            envelope_fingerprint(current), candidate.expected_fingerprint
        ):
            raise CredentialMigrationConflict("credential_envelope_changed")
        profile.wrapped_data_key = candidate.encrypted.wrapped_key
        profile.encryption_key_version = candidate.encrypted.key_version
        audit = SqlGatewayCredentialRewrapAudit(
            profile_id=profile.id,
            credential_version=profile.credential_version,
            source_key_version=snapshot.encrypted.key_version,
            target_key_version=candidate.encrypted.key_version,
            source_fingerprint=candidate.expected_fingerprint,
        )
        session.add(audit)
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(audit)
    return audit

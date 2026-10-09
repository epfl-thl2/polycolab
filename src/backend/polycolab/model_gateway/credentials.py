"""Envelope encryption and secret-safe gateway profile primitives."""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from polycolab.platform.config import KmsProvider, Settings


class CredentialError(Exception):
    pass


class KeyWrapper(Protocol):
    @property
    def key_version(self) -> str: ...

    def wrap(self, plaintext_key: bytes, context: bytes) -> bytes: ...

    def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes: ...


@dataclass(frozen=True)
class LocalAesGcmKeyWrapper:
    """Development/test-only KEK wrapper. Settings reject it outside local."""

    master_key: bytes
    key_version: str = "local-v1"

    def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self.master_key).encrypt(nonce, plaintext_key, context)

    def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
        try:
            return AESGCM(self.master_key).decrypt(wrapped_key[:12], wrapped_key[12:], context)
        except Exception as exc:  # Cryptography deliberately avoids granular errors here.
            raise CredentialError("credential_decryption_failed") from exc


@dataclass(frozen=True)
class AwsKmsKeyWrapper:
    """Concrete AWS KMS adapter; boto3 is imported only in AWS deployments."""

    key_id: str
    key_version: str
    region_name: str | None = None

    def _client(self) -> Any:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise CredentialError("aws_kms_sdk_unavailable") from exc
        return boto3.client("kms", region_name=self.region_name)

    def wrap(self, plaintext_key: bytes, context: bytes) -> bytes:
        try:
            response = self._client().encrypt(
                KeyId=self.key_id,
                Plaintext=plaintext_key,
                EncryptionContext={"polycolab": context.hex()},
            )
            return bytes(response["CiphertextBlob"])
        except CredentialError:
            raise
        except Exception as exc:  # pragma: no cover - requires live AWS KMS
            raise CredentialError("credential_encryption_failed") from exc

    def unwrap(self, wrapped_key: bytes, context: bytes) -> bytes:
        try:
            response = self._client().decrypt(
                CiphertextBlob=wrapped_key, EncryptionContext={"polycolab": context.hex()}
            )
            return bytes(response["Plaintext"])
        except CredentialError:
            raise
        except Exception as exc:  # pragma: no cover - requires live AWS KMS
            raise CredentialError("credential_decryption_failed") from exc


@dataclass(frozen=True)
class EncryptedCredential:
    ciphertext: bytes
    wrapped_key: bytes
    key_version: str


def credential_context(*, user_id: UUID, profile_id: UUID) -> bytes:
    return f"polycolab:gateway-profile:{user_id}:{profile_id}".encode("ascii")


def encrypt_credential(wrapper: KeyWrapper, *, context: bytes, secret: str) -> EncryptedCredential:
    data_key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    ciphertext = nonce + AESGCM(data_key).encrypt(nonce, secret.encode("utf-8"), context)
    return EncryptedCredential(ciphertext, wrapper.wrap(data_key, context), wrapper.key_version)


def decrypt_credential(
    wrapper: KeyWrapper, *, context: bytes, encrypted: EncryptedCredential
) -> str:
    selected = wrapper
    if encrypted.key_version != wrapper.key_version:
        version_router = getattr(wrapper, "wrapper", None)
        if version_router is None:
            raise CredentialError("credential_key_version_unavailable")
        selected = version_router(encrypted.key_version)
    data_key = selected.unwrap(encrypted.wrapped_key, context)
    try:
        return (
            AESGCM(data_key)
            .decrypt(encrypted.ciphertext[:12], encrypted.ciphertext[12:], context)
            .decode("utf-8")
        )
    except Exception as exc:
        raise CredentialError("credential_decryption_failed") from exc


def local_master_key(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise CredentialError("invalid_local_master_key") from exc
    if len(decoded) != 32:
        raise CredentialError("invalid_local_master_key")
    return decoded


def wrapper_from_settings(settings: Settings) -> KeyWrapper:
    if settings.kms_provider is KmsProvider.OPENBAO:
        from polycolab.model_gateway.migration import CredentialKeyring
        from polycolab.model_gateway.openbao import OpenBaoKeyWrapper

        assert settings.openbao_url is not None
        assert settings.openbao_token is not None
        base_url = str(settings.openbao_url).rstrip("/")
        token = settings.openbao_token.get_secret_value()

        def openbao(version: int) -> OpenBaoKeyWrapper:
            return OpenBaoKeyWrapper(
                base_url=base_url,
                token=token,
                backend_id=settings.openbao_backend_id,
                environment=settings.app_env.value,
                mount=settings.openbao_mount,
                key_name=settings.openbao_key_name,
                transit_version=version,
                allow_loopback_http=settings.openbao_allow_loopback_http,
            )

        target = openbao(settings.openbao_transit_version)
        wrappers: list[KeyWrapper] = []
        if settings.legacy_aws_kms_key_id is not None:
            assert settings.legacy_aws_kms_key_version is not None
            wrappers.append(
                AwsKmsKeyWrapper(
                    settings.legacy_aws_kms_key_id,
                    settings.legacy_aws_kms_key_version,
                    settings.legacy_aws_kms_region,
                )
            )
        wrappers.extend(
            openbao(version) for version in settings.openbao_historical_transit_versions
        )
        wrappers.append(target)
        return CredentialKeyring(wrappers, active_version=target.key_version)
    if settings.kms_provider is KmsProvider.AWS:
        assert settings.kms_key_id is not None
        return AwsKmsKeyWrapper(settings.kms_key_id, settings.kms_key_version, settings.kms_region)
    if settings.local_credential_master_key is None:
        # An ephemeral local key is intentionally never persisted; it makes a
        # misconfigured local deployment fail closed after restart rather than
        # silently storing plaintext. Tests inject a stable key when needed.
        return LocalAesGcmKeyWrapper(AESGCM.generate_key(bit_length=256))
    return LocalAesGcmKeyWrapper(local_master_key(settings.local_credential_master_key))

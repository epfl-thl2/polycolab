"""Mock Transit protocol and local envelope cryptography; not live service evidence."""

import base64
import hashlib
import json
import os
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import AnyUrl, SecretStr

from polycolab.model_gateway import openbao as openbao_credentials
from polycolab.model_gateway.credentials import (
    AwsKmsKeyWrapper,
    CredentialError,
    LocalAesGcmKeyWrapper,
    credential_context,
    decrypt_credential,
    encrypt_credential,
    wrapper_from_settings,
)
from polycolab.model_gateway.migration import CredentialKeyring, envelope_fingerprint
from polycolab.model_gateway.openbao import OpenBaoKeyWrapper
from polycolab.platform.config import KmsProvider, Settings


class Transit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.policy: dict[str, object] = {
            "type": "aes256-gcm96",
            "derived": True,
            "exportable": False,
            "allow_plaintext_backup": False,
            "deletion_allowed": False,
            "convergent_encryption": False,
            "keys": {"1": 1, "2": 2},
        }
        self.encryption_version: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["x-vault-token"] == "test-token"
        self.calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"data": self.policy})
        payload = json.loads(request.content)
        assert payload["associated_data"] == payload["context"]
        context = base64.b64decode(payload["context"])
        if "/encrypt/" in request.url.path:
            version = self.encryption_version or payload["key_version"]
            key = hashlib.sha256(str(version).encode() + context).digest()
            nonce = os.urandom(12)
            encrypted = nonce + AESGCM(key).encrypt(
                nonce, base64.b64decode(payload["plaintext"]), context
            )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "ciphertext": f"vault:v{version}:" + base64.b64encode(encrypted).decode()
                    }
                },
            )
        raw = payload["ciphertext"].split(":", 2)
        version = int(raw[1][1:])
        key = hashlib.sha256(str(version).encode() + context).digest()
        encrypted = base64.b64decode(raw[2])
        try:
            plaintext = AESGCM(key).decrypt(encrypted[:12], encrypted[12:], context)
        except InvalidTag:
            return httpx.Response(400, text="untrusted secret-bearing upstream error")
        return httpx.Response(
            200, json={"data": {"plaintext": base64.b64encode(plaintext).decode()}}
        )


def wrapper(service: Transit, **overrides: Any) -> OpenBaoKeyWrapper:
    values: dict[str, Any] = dict(
        base_url="https://bao.example",
        token="test-token",
        backend_id="primary",
        environment="production",
        key_name="gateway",
        transit_version=1,
        transport=httpx.MockTransport(service),
    )
    values.update(overrides)
    return OpenBaoKeyWrapper(**values)


def test_context_environment_and_explicit_version() -> None:
    service = Transit()
    first = wrapper(service)
    second = wrapper(service, environment="staging")
    try:
        context = credential_context(user_id=uuid4(), profile_id=uuid4())
        encrypted = encrypt_credential(first, context=context, secret="provider-secret")
        assert encrypted.key_version == "openbao:v1:primary:production:transit:gateway:1"
        assert decrypt_credential(first, context=context, encrypted=encrypted) == "provider-secret"
        with pytest.raises(CredentialError):
            first.unwrap(encrypted.wrapped_key, b"different-owner-profile")
        with pytest.raises(CredentialError):
            second.unwrap(encrypted.wrapped_key, context)
        assert "test-token" not in repr(first)
        assert all(
            method == "GET" or "/encrypt/" in path or "/decrypt/" in path
            for method, path in service.calls
        )
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("derived", False),
        ("exportable", True),
        ("allow_plaintext_backup", True),
        ("convergent_encryption", True),
        ("deletion_allowed", True),
        ("type", "rsa-2048"),
        ("keys", {}),
    ],
)
def test_unsafe_key_policy_denied_before_encrypt(field: str, value: object) -> None:
    service = Transit()
    service.policy[field] = value
    current = wrapper(service)
    try:
        with pytest.raises(CredentialError, match="key_service_policy_invalid"):
            current.wrap(b"a" * 32, b"context")
        assert service.calls == [("GET", "/v1/transit/keys/gateway")]
    finally:
        current.close()


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "http://bao.example"},
        {"base_url": "https://user:password@bao.example"},
        {"base_url": "https://bao.example/path"},
        {"base_url": "https://bao.example?secret=x"},
        {"key_name": "../gateway"},
        {"transit_version": 0},
        {"transit_version": True},
        {"token": "bad\nheader"},
    ],
)
def test_invalid_configuration(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        wrapper(Transit(), **change)


def test_rotation_retains_exact_old_reader_and_rejects_silent_latest() -> None:
    service = Transit()
    old, new = wrapper(service), wrapper(service, transit_version=2)
    try:
        context = b"owner-profile"
        encrypted = encrypt_credential(old, context=context, secret="provider-secret")
        ring = CredentialKeyring([old, new], active_version=new.key_version)
        fresh = encrypt_credential(ring, context=context, secret="new-provider-secret")
        assert fresh.key_version == new.key_version
        assert decrypt_credential(ring, context=context, encrypted=encrypted) == "provider-secret"
        assert decrypt_credential(ring, context=context, encrypted=fresh) == "new-provider-secret"
        candidate = ring.prepare_rewrap(
            context=context, encrypted=encrypted, target_version=new.key_version
        )
        assert candidate.expected_fingerprint == envelope_fingerprint(encrypted)
        assert candidate.encrypted.ciphertext == encrypted.ciphertext
        assert candidate.encrypted.wrapped_key != encrypted.wrapped_key
        assert ring.decrypt(context=context, encrypted=encrypted) == "provider-secret"
        assert ring.decrypt(context=context, encrypted=candidate.encrypted) == "provider-secret"
        service.encryption_version = 2
        with pytest.raises(CredentialError, match="credential_key_version_unavailable"):
            old.wrap(b"a" * 32, context)
    finally:
        old.close()
        new.close()


def test_application_settings_retain_exact_historical_openbao_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = Transit()

    def configured(**values: Any) -> OpenBaoKeyWrapper:
        assert values["base_url"] == "https://bao.example"
        assert values["backend_id"] == "primary"
        assert values["environment"] == "local"
        return wrapper(
            service,
            backend_id=values["backend_id"],
            environment=values["environment"],
            mount=values["mount"],
            key_name=values["key_name"],
            transit_version=values["transit_version"],
        )

    monkeypatch.setattr(openbao_credentials, "OpenBaoKeyWrapper", configured)
    selected = wrapper_from_settings(
        Settings(
            kms_provider=KmsProvider.OPENBAO,
            openbao_url=AnyUrl("https://bao.example"),
            openbao_token=SecretStr("configured-token"),
            openbao_transit_version=2,
            openbao_historical_transit_versions=[1],
        )
    )
    assert isinstance(selected, CredentialKeyring)
    context = credential_context(user_id=uuid4(), profile_id=uuid4())
    old = selected.wrapper("openbao:v1:primary:local:transit:gateway:1")
    old_envelope = encrypt_credential(old, context=context, secret="old-secret")
    new_envelope = encrypt_credential(selected, context=context, secret="new-secret")
    assert decrypt_credential(selected, context=context, encrypted=old_envelope) == "old-secret"
    assert decrypt_credential(selected, context=context, encrypted=new_envelope) == "new-secret"
    with pytest.raises(CredentialError, match="credential_key_version_unavailable"):
        selected.wrapper("openbao:v1:primary:local:transit:gateway:3")
    selected.close()


def test_migration_preserves_legacy_and_failure_does_not_mutate_original() -> None:
    legacy = LocalAesGcmKeyWrapper(b"a" * 32, "legacy-test-v1")
    service = Transit()
    target = wrapper(service)
    try:
        original = encrypt_credential(legacy, context=b"original-context", secret="provider-secret")
        ring = CredentialKeyring([legacy, target])
        candidate = ring.prepare_rewrap(
            context=b"original-context",
            encrypted=original,
            target_version=target.key_version,
        )
        assert (
            ring.decrypt(context=b"original-context", encrypted=candidate.encrypted)
            == "provider-secret"
        )
        fingerprint = envelope_fingerprint(original)
        service.policy["keys"] = {}
        with pytest.raises(CredentialError):
            ring.prepare_rewrap(
                context=b"original-context",
                encrypted=original,
                target_version=target.key_version,
            )
        assert envelope_fingerprint(original) == fingerprint
        assert ring.decrypt(context=b"original-context", encrypted=original) == "provider-secret"
        with pytest.raises(CredentialError):
            ring.prepare_rewrap(
                context=b"wrong-context",
                encrypted=original,
                target_version=target.key_version,
            )
        corrupt = replace(
            original,
            ciphertext=original.ciphertext[:-1] + bytes([original.ciphertext[-1] ^ 1]),
        )
        with pytest.raises(CredentialError):
            ring.prepare_rewrap(
                context=b"original-context",
                encrypted=corrupt,
                target_version=target.key_version,
            )
        with pytest.raises(CredentialError):
            ring.wrapper("unknown-version")
        with pytest.raises(ValueError):
            CredentialKeyring([legacy, legacy])
        with pytest.raises(ValueError, match="active envelope version"):
            CredentialKeyring([legacy], active_version="missing")
    finally:
        target.close()


def test_supported_aws_envelope_migrates_without_losing_old_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local = LocalAesGcmKeyWrapper(b"a" * 32)

    class Kms:
        def encrypt(self, **kwargs: Any) -> dict[str, bytes]:
            return {
                "CiphertextBlob": local.wrap(
                    kwargs["Plaintext"],
                    bytes.fromhex(kwargs["EncryptionContext"]["polycolab"]),
                )
            }

        def decrypt(self, **kwargs: Any) -> dict[str, bytes]:
            return {
                "Plaintext": local.unwrap(
                    kwargs["CiphertextBlob"],
                    bytes.fromhex(kwargs["EncryptionContext"]["polycolab"]),
                )
            }

    monkeypatch.setattr(AwsKmsKeyWrapper, "_client", lambda self: Kms())
    aws = AwsKmsKeyWrapper("test-key", "existing-aws-v1")
    target = wrapper(Transit())
    try:
        original = encrypt_credential(
            aws, context=b"existing-profile-context", secret="provider-secret"
        )
        ring = CredentialKeyring([aws, target])
        candidate = ring.prepare_rewrap(
            context=b"existing-profile-context",
            encrypted=original,
            target_version=target.key_version,
        )
        assert candidate.encrypted.ciphertext == original.ciphertext
        assert (
            ring.decrypt(context=b"existing-profile-context", encrypted=original)
            == "provider-secret"
        )
        assert (
            ring.decrypt(context=b"existing-profile-context", encrypted=candidate.encrypted)
            == "provider-secret"
        )
    finally:
        target.close()


@pytest.mark.parametrize(
    "status,body",
    [
        (302, b"redirect-secret"),
        (403, b"denied-secret"),
        (503, b"service-secret"),
        (200, b"x" * 16385),
        (200, b"invalid json"),
        (200, b'{"data": []}'),
    ],
)
def test_transport_failures_are_bounded_and_sanitized(status: int, body: bytes) -> None:
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(status, content=body, headers={"Location": "https://other.example"})

    current = wrapper(Transit(), transport=httpx.MockTransport(respond))
    try:
        with pytest.raises(CredentialError) as error:
            current.wrap(b"a" * 32, b"context")
        assert "secret" not in str(error.value) and len(calls) == 1
        assert error.value.__cause__ is None
    finally:
        current.close()

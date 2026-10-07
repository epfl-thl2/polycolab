from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from polycolab.db.models import (
    SqlGatewayCredentialRewrapAudit,
    SqlGatewayProfile,
    SqlGatewayRunGrant,
)
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    AwsKmsKeyWrapper,
    CredentialError,
    LocalAesGcmKeyWrapper,
    credential_context,
    decrypt_credential,
    encrypt_credential,
)
from polycolab.model_gateway.migration import (
    CredentialKeyring,
    CredentialMigrationConflict,
    commit_rewrap_candidate,
    rewrap_snapshot_page,
)
from polycolab.model_gateway.service import (
    GatewayLimits,
    GrantInvalid,
    ProviderFailure,
    UnsafeBaseUrl,
    exchange_run_grant,
    issue_run_grant,
    request_model,
    validate_base_url,
)
from polycolab.model_gateway.transport import ProviderTransportError
from polycolab.platform.logging import redact_secrets


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class RecordingProvider:
    def __init__(self, response: dict[str, object] | None = None) -> None:
        self.response = response or {
            "choices": [{"message": {"role": "assistant", "content": "OK"}}],
            "usage": {"completion_tokens": 1},
        }
        self.calls: list[dict[str, object]] = []

    def request_json(
        self, *, base_url: str, api_key: str, payload: dict[str, object]
    ) -> dict[str, object]:
        self.calls.append({"base_url": base_url, "api_key": api_key, "payload": payload})
        return self.response


def app_for(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


def create_gateway_profile(client: TestClient, token: str = "owner") -> dict[str, Any]:
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=headers(token),
        json={
            "display_name": "Primary model",
            "wire_api": "chat_completions",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "research-model",
            "api_key": "sk-super-secret-value",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def test_credential_rewrap_is_bounded_audited_and_compare_and_swap(
    client: TestClient,
) -> None:
    created = create_gateway_profile(client)
    app = app_for(client)
    target = LocalAesGcmKeyWrapper(b"b" * 32, "replacement-v2")
    ring = CredentialKeyring([app.state.credential_wrapper, target])

    with app.state.session_factory() as db:
        snapshots = rewrap_snapshot_page(db, target_version=target.key_version, limit=1)
        assert len(snapshots) == 1
        snapshot = snapshots[0]
        db.rollback()  # Key-service work happens after the read transaction ends.
        candidate = ring.prepare_rewrap(
            context=credential_context(user_id=snapshot.user_id, profile_id=snapshot.profile_id),
            encrypted=snapshot.encrypted,
            target_version=target.key_version,
        )
        audit = commit_rewrap_candidate(db, snapshot=snapshot, candidate=candidate)
        stored = db.get(SqlGatewayProfile, UUID(created["id"]))
        assert stored is not None
        assert stored.encryption_key_version == target.key_version
        assert stored.encrypted_credential == snapshot.encrypted.ciphertext
        assert audit.source_key_version == snapshot.encrypted.key_version
        assert audit.target_key_version == target.key_version
        assert db.scalar(select(SqlGatewayCredentialRewrapAudit)) is not None

    with app.state.session_factory() as db:
        assert rewrap_snapshot_page(db, target_version=target.key_version) == []


def test_credential_rewrap_rejects_concurrent_rotation_without_audit(
    client: TestClient,
) -> None:
    create_gateway_profile(client)
    app = app_for(client)
    target = LocalAesGcmKeyWrapper(b"c" * 32, "replacement-v3")
    ring = CredentialKeyring([app.state.credential_wrapper, target])
    with app.state.session_factory() as db:
        snapshot = rewrap_snapshot_page(db, target_version=target.key_version)[0]
        db.rollback()
        candidate = ring.prepare_rewrap(
            context=credential_context(user_id=snapshot.user_id, profile_id=snapshot.profile_id),
            encrypted=snapshot.encrypted,
            target_version=target.key_version,
        )
        profile = db.get(SqlGatewayProfile, snapshot.profile_id)
        assert profile is not None
        profile.credential_version += 1
        db.commit()
        with pytest.raises(CredentialMigrationConflict, match="credential_envelope_changed"):
            commit_rewrap_candidate(db, snapshot=snapshot, candidate=candidate)
        assert db.scalar(select(SqlGatewayCredentialRewrapAudit)) is None


def test_envelope_ciphertext_is_not_plaintext_and_context_bound() -> None:
    wrapper = LocalAesGcmKeyWrapper(b"a" * 32)
    context = credential_context(user_id=uuid4(), profile_id=uuid4())
    encrypted = encrypt_credential(wrapper, context=context, secret="sk-live-secret")
    assert b"sk-live-secret" not in encrypted.ciphertext
    assert decrypt_credential(wrapper, context=context, encrypted=encrypted) == "sk-live-secret"
    with pytest.raises(CredentialError):
        decrypt_credential(wrapper, context=b"other", encrypted=encrypted)


def test_aws_kms_wrapper_uses_key_and_encryption_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeKms:
        calls: list[tuple[str, dict[str, object]]] = []

        def encrypt(self, **kwargs: object) -> dict[str, bytes]:
            self.calls.append(("encrypt", kwargs))
            return {"CiphertextBlob": b"wrapped"}

        def decrypt(self, **kwargs: object) -> dict[str, bytes]:
            self.calls.append(("decrypt", kwargs))
            return {"Plaintext": b"data-key"}

    fake = FakeKms()
    monkeypatch.setattr(AwsKmsKeyWrapper, "_client", lambda _self: fake)
    wrapper = AwsKmsKeyWrapper("arn:aws:kms:key", "kms-v1", "eu-central-1")
    context = b"profile-context"

    assert wrapper.wrap(b"data-key", context) == b"wrapped"
    assert wrapper.unwrap(b"wrapped", context) == b"data-key"
    assert fake.calls == [
        (
            "encrypt",
            {
                "KeyId": "arn:aws:kms:key",
                "Plaintext": b"data-key",
                "EncryptionContext": {"polycolab": context.hex()},
            },
        ),
        (
            "decrypt",
            {
                "CiphertextBlob": b"wrapped",
                "EncryptionContext": {"polycolab": context.hex()},
            },
        ),
    ]


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1", "https://user:pass@example.test", "https://169.254.169.254"],
)
def test_base_url_rejects_private_or_credentialed_targets(url: str) -> None:
    def private_dns(*_args: object) -> list[tuple[object, ...]]:
        return [(0, 0, 0, "", ("127.0.0.1", 443))]

    with pytest.raises(UnsafeBaseUrl):
        validate_base_url(url, production=True, resolver=private_dns)


def test_base_url_allows_public_https_with_injected_dns() -> None:
    def public_dns(*_args: object) -> list[tuple[object, ...]]:
        return [(0, 0, 0, "", ("8.8.8.8", 443))]

    assert (
        validate_base_url("https://provider.example", production=True, resolver=public_dns)
        == "https://provider.example"
    )


def test_log_redaction_never_serializes_provider_secrets() -> None:
    event = redact_secrets(
        None, "info", {"api_key": "sk-live", "nested": {"Authorization": "Bearer x"}}
    )
    assert event == {"api_key": "[REDACTED]", "nested": {"Authorization": "[REDACTED]"}}
    rendered = redact_secrets(
        None,
        "error",
        {"event": "request failed with Bearer abc.def.ghi and sk-secretvalue"},
    )
    assert "abc.def.ghi" not in str(rendered)
    assert "sk-secretvalue" not in str(rendered)


def test_profile_routes_encrypt_never_read_back_validate_rotate_and_delete(
    client: TestClient,
) -> None:
    created = create_gateway_profile(client)
    assert "api_key" not in created
    assert "encrypted_credential" not in created
    assert "wrapped_data_key" not in created

    session = app_for(client).state.session_factory()
    try:
        stored = session.get(SqlGatewayProfile, UUID(created["id"]))
        assert stored is not None
        assert b"sk-super-secret-value" not in stored.encrypted_credential
        first_ciphertext = stored.encrypted_credential
    finally:
        session.close()

    provider = RecordingProvider()
    app_for(client).state.provider_transport = provider
    validated = client.post(
        f"/api/v1/gateway/profiles/{created['id']}/validate", headers=headers("owner")
    )
    assert validated.status_code == 200
    assert provider.calls[0]["api_key"] == "sk-super-secret-value"
    assert "sk-super-secret-value" not in validated.text

    rotated = client.post(
        f"/api/v1/gateway/profiles/{created['id']}/rotate",
        headers=headers("owner"),
        json={"api_key": "sk-rotated-secret"},
    )
    assert rotated.status_code == 200
    assert "sk-rotated-secret" not in rotated.text
    session = app_for(client).state.session_factory()
    try:
        stored = session.get(SqlGatewayProfile, UUID(created["id"]))
        assert stored is not None
        assert stored.credential_version == 2
        assert stored.encrypted_credential != first_ciphertext
    finally:
        session.close()

    assert client.get("/api/v1/gateway/profiles", headers=headers("outsider")).json() == []
    assert (
        client.post(
            f"/api/v1/gateway/profiles/{created['id']}/rotate",
            headers=headers("outsider"),
            json={"api_key": "sk-cross-user"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/gateway/profiles/{created['id']}", headers=headers("owner")
        ).status_code
        == 204
    )
    assert client.get("/api/v1/gateway/profiles", headers=headers("owner")).json() == []


def test_profile_validation_failure_is_normalized_and_secret_safe(
    client: TestClient,
) -> None:
    created = create_gateway_profile(client)

    class FailingProvider:
        def request_json(self, **_kwargs: object) -> dict[str, object]:
            raise ProviderTransportError("provider_rejected")

    app_for(client).state.provider_transport = FailingProvider()
    response = client.post(
        f"/api/v1/gateway/profiles/{created['id']}/validate", headers=headers("owner")
    )
    assert response.status_code == 422
    assert "secret" not in response.text.casefold()


def test_profile_creation_rolls_back_when_key_service_is_unavailable(
    client: TestClient,
) -> None:
    class FailingWrapper:
        key_version = "failed-v1"

        def wrap(self, _plaintext_key: bytes, _context: bytes) -> bytes:
            raise CredentialError("credential_encryption_failed")

        def unwrap(self, _wrapped_key: bytes, _context: bytes) -> bytes:
            raise AssertionError("not used")

    app_for(client).state.credential_wrapper = FailingWrapper()
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=headers("owner"),
        json={
            "display_name": "Unavailable KMS",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "research-model",
            "api_key": "sk-must-not-persist",
        },
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "credential_unavailable"
    session = app_for(client).state.session_factory()
    try:
        assert list(session.scalars(select(SqlGatewayProfile))) == []
    finally:
        session.close()


def test_run_grant_is_scoped_one_use_expiring_and_invalidated_by_rotation(
    client: TestClient,
) -> None:
    created = create_gateway_profile(client)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    profile_id = UUID(created["id"])
    run_id = uuid4()
    session = app_for(client).state.session_factory()
    try:
        token = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=run_id,
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=300,
        )
        assert token != "sk-super-secret-value"
        persisted = session.scalar(
            select(SqlGatewayRunGrant).where(
                SqlGatewayRunGrant.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert persisted is not None
        assert token not in repr(persisted.__dict__)
        assert "sk-super-secret-value" not in repr(persisted.__dict__)
        with pytest.raises(GrantInvalid):
            exchange_run_grant(
                session,
                token=token,
                run_id=uuid4(),
                user_id=user_id,
                model_id="research-model",
            )
        assert not session.in_transaction()
        grant = exchange_run_grant(
            session,
            token=token,
            run_id=run_id,
            user_id=user_id,
            model_id="research-model",
        )
        assert grant.used_at is not None
        with pytest.raises(GrantInvalid):
            exchange_run_grant(
                session,
                token=token,
                run_id=run_id,
                user_id=user_id,
                model_id="research-model",
            )
        with pytest.raises(GrantInvalid):
            issue_run_grant(
                session,
                user_id=user_id,
                profile_id=profile_id,
                run_id=uuid4(),
                model_id="other-model",
                ttl_seconds=60,
                max_ttl_seconds=300,
            )
        with pytest.raises(GrantInvalid):
            issue_run_grant(
                session,
                user_id=user_id,
                profile_id=profile_id,
                run_id=uuid4(),
                model_id="research-model",
                ttl_seconds=301,
                max_ttl_seconds=300,
            )
        expiring = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=uuid4(),
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=300,
        )
        expiring_row = session.scalar(
            select(SqlGatewayRunGrant).where(
                SqlGatewayRunGrant.token_digest == hashlib.sha256(expiring.encode()).hexdigest()
            )
        )
        assert expiring_row is not None
        expiring_row.expires_at = utc_now() - timedelta(seconds=1)
        session.commit()
        with pytest.raises(GrantInvalid):
            exchange_run_grant(
                session,
                token=expiring,
                run_id=expiring_row.run_id,
                user_id=user_id,
                model_id="research-model",
            )
        rotating = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=uuid4(),
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=300,
        )
        rotating_row = session.scalar(
            select(SqlGatewayRunGrant).where(
                SqlGatewayRunGrant.token_digest == hashlib.sha256(rotating.encode()).hexdigest()
            )
        )
        assert rotating_row is not None
        assert (
            client.post(
                f"/api/v1/gateway/profiles/{profile_id}/rotate",
                headers=headers("owner"),
                json={"api_key": "sk-another-rotation"},
            ).status_code
            == 200
        )
        session.expire_all()
        with pytest.raises(GrantInvalid):
            exchange_run_grant(
                session,
                token=rotating,
                run_id=rotating_row.run_id,
                user_id=user_id,
                model_id="research-model",
            )
    finally:
        session.close()


def test_model_gateway_applies_key_and_enforces_input_output_cost_and_usage(
    client: TestClient,
) -> None:
    created = create_gateway_profile(client)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    profile_id = UUID(created["id"])
    limits = GatewayLimits(
        run_token_ttl_seconds=300,
        max_input_bytes=1000,
        max_output_tokens=10,
        max_cost_microusd=1_000_000,
        input_microusd_per_million_tokens=1,
        output_microusd_per_million_tokens=1,
        max_attempts=2,
    )
    session = app_for(client).state.session_factory()
    try:
        run_id = uuid4()
        token = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=run_id,
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=limits.run_token_ttl_seconds,
        )
        provider = RecordingProvider()
        result = request_model(
            session,
            wrapper=app_for(client).state.credential_wrapper,
            token=token,
            run_id=run_id,
            user_id=user_id,
            model_id="research-model",
            messages=[{"role": "user", "content": "hello"}],
            max_output_tokens=10,
            transport=cast(Any, provider),
            limits=limits,
        )
        assert result["choices"]
        assert provider.calls[0]["api_key"] == "sk-super-secret-value"

        excessive_run_id = uuid4()
        excessive_token = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=excessive_run_id,
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=limits.run_token_ttl_seconds,
        )
        with pytest.raises(ProviderFailure, match="provider_output_limit_exceeded"):
            request_model(
                session,
                wrapper=app_for(client).state.credential_wrapper,
                token=excessive_token,
                run_id=excessive_run_id,
                user_id=user_id,
                model_id="research-model",
                messages=[],
                max_output_tokens=10,
                transport=cast(
                    Any,
                    RecordingProvider(
                        {
                            "choices": [],
                            "usage": {"completion_tokens": 11},
                        }
                    ),
                ),
                limits=limits,
            )

        missing_usage_run_id = uuid4()
        missing_usage_token = issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=missing_usage_run_id,
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=limits.run_token_ttl_seconds,
        )
        with pytest.raises(ProviderFailure, match="provider_usage_required"):
            request_model(
                session,
                wrapper=app_for(client).state.credential_wrapper,
                token=missing_usage_token,
                run_id=missing_usage_run_id,
                user_id=user_id,
                model_id="research-model",
                messages=[],
                max_output_tokens=1,
                transport=cast(Any, RecordingProvider({"choices": [{"message": "x"}]})),
                limits=limits,
            )

        failures: tuple[tuple[GatewayLimits, list[dict[str, object]], int, str], ...] = (
            (limits, [{"content": "x" * 2000}], 1, "gateway_input_limit_exceeded"),
            (limits, [], 11, "gateway_output_limit_exceeded"),
            (
                GatewayLimits(300, 1000, 10, 1, 1_000_000, 1_000_000, 2),
                [],
                10,
                "gateway_cost_limit_exceeded",
            ),
        )
        for failure_limits, messages, output, code in failures:
            with pytest.raises(ProviderFailure, match=code):
                request_model(
                    session,
                    wrapper=app_for(client).state.credential_wrapper,
                    token="not-consumed-for-preflight",
                    run_id=uuid4(),
                    user_id=user_id,
                    model_id="research-model",
                    messages=messages,
                    max_output_tokens=output,
                    transport=cast(Any, provider),
                    limits=failure_limits,
                )
    finally:
        session.close()

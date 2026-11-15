"""Internal provider gateway. It owns credentials, never sessions or runners."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import socket
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlGatewayRunGrant, SqlProviderConnection
from polycolab.entities.accounts import IdentifiedUser
from polycolab.entities.time import utc_now
from polycolab.model_gateway.credentials import (
    CredentialError,
    EncryptedCredential,
    KeyWrapper,
    credential_context,
    decrypt_credential,
    encrypt_credential,
)
from polycolab.model_gateway.stream import (
    StreamLimits,
    encode_error_sse,
    encode_sse,
    normalize_model_stream,
)
from polycolab.model_gateway.transport import ProviderTransport, ProviderTransportError


class GatewayNotFound(Exception):
    pass


class UnsafeBaseUrl(Exception):
    pass


class GrantInvalid(Exception):
    pass


class ProviderFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class GatewayLimits:
    run_token_ttl_seconds: int
    max_input_bytes: int
    max_output_tokens: int
    max_cost_microusd: int
    input_microusd_per_million_tokens: int
    output_microusd_per_million_tokens: int
    max_attempts: int
    max_response_bytes: int = 1_000_000


def _is_expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value <= utc_now()


def validate_base_url(value: str, *, production: bool, resolver=socket.getaddrinfo) -> str:  # type: ignore[no-untyped-def]
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise UnsafeBaseUrl
    if production and parsed.scheme != "https":
        raise UnsafeBaseUrl
    if parsed.query or parsed.fragment:
        raise UnsafeBaseUrl
    try:
        addresses = resolver(
            parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
        )
    except OSError as exc:
        raise UnsafeBaseUrl from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise UnsafeBaseUrl
    return value.rstrip("/")


def connection_for_user(
    session: Session, *, provider_connection_id: UUID, user_id: UUID, lock: bool = False
) -> SqlProviderConnection:
    statement = select(SqlProviderConnection).where(
        SqlProviderConnection.id == provider_connection_id,
        SqlProviderConnection.user_id == user_id,
        SqlProviderConnection.deleted_at.is_(None),
    )
    if lock:
        statement = statement.with_for_update()
    connection = session.scalar(statement)
    if connection is None:
        raise GatewayNotFound
    return connection


def _api_key_preview(api_key: str) -> str:
    """Expose only a bounded recognition hint, never an entire short key."""
    if len(api_key) >= 12:
        return f"{api_key[:3]}••••{api_key[-4:]}"
    if len(api_key) >= 5:
        return f"••••{api_key[-4:]}"
    return "••••"


def create_connection(
    session: Session,
    *,
    user: IdentifiedUser,
    wrapper: KeyWrapper,
    display_name: str,
    base_url: str,
    model_id: str,
    api_key: str,
    production: bool,
    wire_api: str = "responses",
) -> SqlProviderConnection:
    if wire_api not in {"responses", "chat_completions"}:
        raise ValueError("unsupported provider protocol")
    connection = SqlProviderConnection(
        user_id=user.id,
        display_name=display_name,
        base_url=validate_base_url(base_url, production=production),
        model_id=model_id,
        wire_api=wire_api,
        api_key_preview=_api_key_preview(api_key),
        credential_version=1,
        encrypted_credential=b"",
        wrapped_data_key=b"",
        encryption_key_version=wrapper.key_version,
    )
    try:
        session.add(connection)
        session.flush()
        encrypted = encrypt_credential(
            wrapper,
            context=credential_context(user_id=user.id, provider_connection_id=connection.id),
            secret=api_key,
        )
        connection.encrypted_credential = encrypted.ciphertext
        connection.wrapped_data_key = encrypted.wrapped_key
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(connection)
    return connection


def rotate_connection(
    session: Session,
    *,
    provider_connection_id: UUID,
    user: IdentifiedUser,
    wrapper: KeyWrapper,
    api_key: str,
) -> SqlProviderConnection:
    try:
        connection = connection_for_user(
            session, provider_connection_id=provider_connection_id, user_id=user.id, lock=True
        )
        encrypted = encrypt_credential(
            wrapper,
            context=credential_context(user_id=user.id, provider_connection_id=connection.id),
            secret=api_key,
        )
        connection.encrypted_credential, connection.wrapped_data_key = (
            encrypted.ciphertext,
            encrypted.wrapped_key,
        )
        connection.encryption_key_version = encrypted.key_version
        connection.api_key_preview = _api_key_preview(api_key)
        connection.credential_version += 1
        for grant in session.scalars(
            select(SqlGatewayRunGrant).where(
                SqlGatewayRunGrant.provider_connection_id == connection.id,
                SqlGatewayRunGrant.used_at.is_(None),
            )
        ):
            grant.revoked = True
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(connection)
    return connection


def delete_connection(
    session: Session, *, provider_connection_id: UUID, user: IdentifiedUser
) -> None:
    connection = connection_for_user(
        session, provider_connection_id=provider_connection_id, user_id=user.id, lock=True
    )
    connection.deleted_at = utc_now()
    connection.api_key_preview = None
    connection.encrypted_credential = b""
    connection.wrapped_data_key = b""
    for grant in session.scalars(
        select(SqlGatewayRunGrant).where(
            SqlGatewayRunGrant.provider_connection_id == connection.id,
            SqlGatewayRunGrant.used_at.is_(None),
        )
    ):
        grant.revoked = True
    session.commit()


def issue_run_grant(
    session: Session,
    *,
    user_id: UUID,
    provider_connection_id: UUID,
    run_id: UUID,
    model_id: str,
    ttl_seconds: int,
    max_ttl_seconds: int,
    expected_credential_version: int | None = None,
) -> str:
    if ttl_seconds < 1 or ttl_seconds > max_ttl_seconds:
        raise GrantInvalid
    connection = connection_for_user(
        session, provider_connection_id=provider_connection_id, user_id=user_id, lock=True
    )
    if connection.model_id != model_id or (
        expected_credential_version is not None
        and connection.credential_version != expected_credential_version
    ):
        raise GrantInvalid
    token = secrets.token_urlsafe(32)
    session.add(
        SqlGatewayRunGrant(
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            user_id=user_id,
            provider_connection_id=provider_connection_id,
            run_id=run_id,
            model_id=model_id,
            credential_version=connection.credential_version,
            expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        )
    )
    session.commit()
    return token


def exchange_run_grant(
    session: Session, *, token: str, run_id: UUID, user_id: UUID, model_id: str
) -> SqlGatewayRunGrant:
    try:
        digest = _token_digest(token)
        candidate = session.scalar(
            select(SqlGatewayRunGrant).where(SqlGatewayRunGrant.token_digest == digest)
        )
        if candidate is None:
            raise GrantInvalid
        # Profile is the serialization point shared with rotate/delete/issuance.
        connection = session.scalar(
            select(SqlProviderConnection)
            .where(SqlProviderConnection.id == candidate.provider_connection_id)
            .with_for_update()
        )
        grant = session.scalar(
            select(SqlGatewayRunGrant)
            .where(SqlGatewayRunGrant.token_digest == digest)
            .with_for_update()
        )
        if (
            grant is None
            or grant.revoked
            or grant.used_at is not None
            or grant.run_id != run_id
            or grant.user_id != user_id
            or grant.model_id != model_id
            or _is_expired(grant.expires_at)
        ):
            raise GrantInvalid
        if (
            connection is None
            or connection.deleted_at is not None
            or connection.user_id != grant.user_id
            or connection.credential_version != grant.credential_version
        ):
            raise GrantInvalid
        grant.used_at = utc_now()
        session.commit()
        return grant
    except Exception:
        # A failed scope/replay/expiry check must release the connection serialization
        # lock immediately; API request handlers may reuse this database session.
        session.rollback()
        raise


def _token_digest(token: str) -> str:
    if not token or len(token) > 4096 or any(ord(char) < 32 for char in token):
        raise GrantInvalid
    return hashlib.sha256(token.encode()).hexdigest()


def exchange_run_grant_for_model(
    session: Session, *, token: str, run_id: UUID, model_id: str
) -> SqlGatewayRunGrant:
    """Derive identity from the opaque grant; callers cannot submit user_id."""

    try:
        digest = _token_digest(token)
        candidate = session.scalar(
            select(SqlGatewayRunGrant).where(SqlGatewayRunGrant.token_digest == digest)
        )
        if candidate is None:
            raise GrantInvalid
        return exchange_run_grant(
            session,
            token=token,
            run_id=run_id,
            user_id=candidate.user_id,
            model_id=model_id,
        )
    except Exception:
        session.rollback()
        raise


def _request_cost_microusd(
    *, input_bytes: int, max_output_tokens: int, limits: GatewayLimits
) -> int:
    # UTF-8 bytes are a conservative upper bound for token count. Reserve the
    # worst case for every permitted attempt so retries cannot exceed the cap.
    per_attempt = (
        input_bytes * limits.input_microusd_per_million_tokens
        + max_output_tokens * limits.output_microusd_per_million_tokens
        + 999_999
    ) // 1_000_000
    return per_attempt * limits.max_attempts


def _provider_payload(
    *,
    model_id: str,
    messages: list[dict[str, object]],
    max_output_tokens: int,
    include_platform_tools: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_output_tokens,
    }
    if include_platform_tools:
        # Import here to preserve the model-gateway's ownership of provider I/O
        # while keeping fixed tool schemas owned by the scoped tools boundary.
        from polycolab.agents.tools import PLATFORM_TOOL_DEFINITIONS

        payload["tools"] = list(PLATFORM_TOOL_DEFINITIONS)
        payload["tool_choice"] = "auto"
    return payload


def _validate_provider_payload(payload: dict[str, object], max_output_tokens: int) -> None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ProviderFailure("provider_usage_required")
    completion_tokens = usage.get("completion_tokens")
    if (
        not isinstance(completion_tokens, int)
        or isinstance(completion_tokens, bool)
        or completion_tokens < 0
        or completion_tokens > max_output_tokens
    ):
        raise ProviderFailure("provider_output_limit_exceeded")
    choices = payload.get("choices")
    if not isinstance(choices, list):
        raise ProviderFailure("provider_invalid_response")


def request_model(
    session: Session,
    *,
    wrapper: KeyWrapper,
    token: str,
    run_id: UUID,
    user_id: UUID,
    model_id: str,
    messages: list[dict[str, object]],
    max_output_tokens: int,
    transport: ProviderTransport,
    limits: GatewayLimits,
) -> dict[str, object]:
    """Apply a credential only inside the service; callers receive no key."""
    if max_output_tokens < 1 or max_output_tokens > limits.max_output_tokens:
        raise ProviderFailure("gateway_output_limit_exceeded")
    payload = _provider_payload(
        model_id=model_id,
        messages=messages,
        max_output_tokens=max_output_tokens,
    )
    try:
        input_bytes = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ProviderFailure("gateway_request_invalid") from exc
    if input_bytes > limits.max_input_bytes:
        raise ProviderFailure("gateway_input_limit_exceeded")
    if (
        _request_cost_microusd(
            input_bytes=input_bytes,
            max_output_tokens=max_output_tokens,
            limits=limits,
        )
        > limits.max_cost_microusd
    ):
        raise ProviderFailure("gateway_cost_limit_exceeded")
    grant = exchange_run_grant(
        session, token=token, run_id=run_id, user_id=user_id, model_id=model_id
    )
    connection = connection_for_user(
        session, provider_connection_id=grant.provider_connection_id, user_id=user_id
    )
    try:
        credential = decrypt_credential(
            wrapper,
            context=credential_context(user_id=user_id, provider_connection_id=connection.id),
            encrypted=EncryptedCredential(
                connection.encrypted_credential,
                connection.wrapped_data_key,
                connection.encryption_key_version,
            ),
        )
    except CredentialError as exc:
        raise ProviderFailure("credential_unavailable") from exc
    try:
        result = transport.request_json(
            base_url=connection.base_url,
            api_key=credential,
            payload=payload,
        )
        _validate_provider_payload(result, max_output_tokens)
        return result
    except ProviderTransportError as exc:
        raise ProviderFailure(exc.code) from exc
    finally:
        credential = ""


def stream_model(
    session: Session,
    *,
    wrapper: KeyWrapper,
    token: str,
    run_id: UUID,
    model_id: str,
    messages: list[dict[str, object]],
    max_output_tokens: int,
    transport: ProviderTransport,
    limits: GatewayLimits,
) -> Iterator[bytes]:
    """Open one normalized SSE turn while retaining the credential in the gateway."""

    if max_output_tokens < 1 or max_output_tokens > limits.max_output_tokens:
        raise ProviderFailure("gateway_output_limit_exceeded")
    payload = _provider_payload(
        model_id=model_id,
        messages=messages,
        max_output_tokens=max_output_tokens,
        include_platform_tools=True,
    )
    payload.update({"stream": True, "stream_options": {"include_usage": True}})
    from polycolab.agents.tools import definitions
    from polycolab.db.models import SqlAgentRun

    run = session.get(SqlAgentRun, run_id)
    if run is not None:
        payload["tools"] = definitions(session, run)
    try:
        input_bytes = len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ProviderFailure("gateway_request_invalid") from exc
    if input_bytes > limits.max_input_bytes:
        raise ProviderFailure("gateway_input_limit_exceeded")
    if (
        _request_cost_microusd(
            input_bytes=input_bytes,
            max_output_tokens=max_output_tokens,
            limits=limits,
        )
        > limits.max_cost_microusd
    ):
        raise ProviderFailure("gateway_cost_limit_exceeded")
    grant = exchange_run_grant_for_model(session, token=token, run_id=run_id, model_id=model_id)
    if (
        run is None
        or run.requested_by_user_id != grant.user_id
        or run.provider_connection_id != grant.provider_connection_id
        or run.gateway_credential_version != grant.credential_version
    ):
        raise GrantInvalid
    connection = connection_for_user(
        session, provider_connection_id=grant.provider_connection_id, user_id=grant.user_id
    )
    try:
        credential = decrypt_credential(
            wrapper,
            context=credential_context(user_id=grant.user_id, provider_connection_id=connection.id),
            encrypted=EncryptedCredential(
                connection.encrypted_credential,
                connection.wrapped_data_key,
                connection.encryption_key_version,
            ),
        )
    except CredentialError as exc:
        raise ProviderFailure("credential_unavailable") from exc
    try:
        response = transport.open_stream(
            base_url=connection.base_url,
            api_key=credential,
            payload=payload,
        )
    except ProviderTransportError as exc:
        credential = ""
        raise ProviderFailure(exc.code) from exc

    def body() -> Iterator[bytes]:
        nonlocal credential
        try:
            frames = normalize_model_stream(
                response.chunks,
                max_output_tokens=max_output_tokens,
                limits=StreamLimits(
                    max_response_bytes=limits.max_response_bytes,
                    max_content_bytes=limits.max_response_bytes,
                ),
            )
            for frame in frames:
                yield encode_sse(frame)
            yield b"data: [DONE]\n\n"
        except ProviderTransportError as exc:
            yield encode_error_sse(exc.code)
            yield b"data: [DONE]\n\n"
        finally:
            response.close()
            credential = ""

    return body()


def validate_connection_credential(
    *,
    connection: SqlProviderConnection,
    user_id: UUID,
    wrapper: KeyWrapper,
    transport: ProviderTransport,
) -> None:
    """Make one minimal provider call without exposing or retaining the key."""

    credential = decrypt_credential(
        wrapper,
        context=credential_context(user_id=user_id, provider_connection_id=connection.id),
        encrypted=EncryptedCredential(
            connection.encrypted_credential,
            connection.wrapped_data_key,
            connection.encryption_key_version,
        ),
    )
    try:
        if connection.wire_api == "responses":
            from polycolab.model_gateway.responses import completed_response

            stream = transport.open_stream(
                base_url=connection.base_url,
                api_key=credential,
                responses=True,
                payload={
                    "model": connection.model_id,
                    "input": "Reply with OK.",
                    "max_output_tokens": 16,
                    "store": False,
                    "stream": True,
                },
            )
            try:
                completed_response(stream.chunks, max_bytes=65536, max_output_tokens=16)
            finally:
                stream.close()
            return
        payload = transport.request_json(
            base_url=connection.base_url,
            api_key=credential,
            payload={
                "model": connection.model_id,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
            },
        )
        _validate_provider_payload(payload, 1)
    except ProviderTransportError as exc:
        raise ProviderFailure(exc.code) from exc
    finally:
        credential = ""

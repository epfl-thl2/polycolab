from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from polycolab.db.models import SqlGatewayRunGrant
from polycolab.model_gateway.service import (
    GrantInvalid,
    exchange_run_grant_for_model,
    issue_run_grant,
    stream_model,
)
from polycolab.model_gateway.stream import StreamLimits, normalize_model_stream
from polycolab.model_gateway.transport import (
    ProviderStreamResponse,
    ProviderTransport,
    ProviderTransportError,
)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def app_for(client: TestClient) -> FastAPI:
    return cast(FastAPI, client.app)


@dataclass
class FakeStreamTransport:
    body: list[bytes]
    opened: int = 0
    closed: int = 0

    def open_stream(self, **_kwargs: object) -> ProviderStreamResponse:
        self.opened += 1
        chunks = iter(self.body)

        def close() -> None:
            self.closed += 1

        return ProviderStreamResponse(200, chunks, close)


def create_profile(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/v1/gateway/profiles",
        headers=headers("owner"),
        json={
            "display_name": "streaming",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "research-model",
            "api_key": "sk-stream-secret",
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def issue_grant(client: TestClient, profile_id: UUID, run_id: UUID) -> str:
    app = app_for(client)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    session = app.state.session_factory()
    try:
        return issue_run_grant(
            session,
            user_id=user_id,
            profile_id=profile_id,
            run_id=run_id,
            model_id="research-model",
            ttl_seconds=60,
            max_ttl_seconds=300,
        )
    finally:
        session.close()


def install_stream_transport(client: TestClient, body: list[bytes]) -> FakeStreamTransport:
    fake = FakeStreamTransport(body)
    app_for(client).state.provider_transport = ProviderTransport(
        resolver=lambda _host, _port: ("93.184.216.34",),
        stream_transport=fake,
        retry_count=0,
    )
    return fake


def test_private_stream_normalizes_provider_frames_and_consumes_grant(
    client: TestClient,
) -> None:
    profile = create_profile(client)
    run_id = uuid4()
    token = issue_grant(client, UUID(profile["id"]), run_id)
    fake = install_stream_transport(
        client,
        [
            b'data: {"id":"provider-id","choices":[{"delta":{"content":"Hi"}}]}\n\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            b'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n',
            b"data: [DONE]\n\n",
        ],
    )

    response = client.post(
        "/internal/v1/model/chat/completions",
        headers=headers(token),
        json={
            "run_id": str(run_id),
            "model_id": "research-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 4,
        },
    )

    assert response.status_code == 200, response.text
    assert '"content":"Hi"' in response.text
    assert "provider-id" not in response.text
    assert '"completion_tokens":1' in response.text
    assert response.text.endswith("data: [DONE]\n\n")
    assert fake.opened == 1
    assert fake.closed == 1

    replay = client.post(
        "/internal/v1/model/chat/completions",
        headers=headers(token),
        json={
            "run_id": str(run_id),
            "model_id": "research-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 4,
        },
    )
    assert replay.status_code == 401


def test_private_stream_rejects_tools_before_consuming_grant(client: TestClient) -> None:
    profile = create_profile(client)
    run_id = uuid4()
    token = issue_grant(client, UUID(profile["id"]), run_id)
    fake = install_stream_transport(client, [])
    response = client.post(
        "/internal/v1/model/chat/completions",
        headers=headers(token),
        json={
            "run_id": str(run_id),
            "model_id": "research-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 4,
            "tools": [],
        },
    )
    assert response.status_code == 422
    assert fake.opened == 0

    session = app_for(client).state.session_factory()
    try:
        row = session.scalar(
            select(SqlGatewayRunGrant).where(
                SqlGatewayRunGrant.token_digest == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        assert row is not None and row.used_at is None
    finally:
        session.close()


def test_stream_parser_failure_is_stable_and_closes_provider(client: TestClient) -> None:
    profile = create_profile(client)
    run_id = uuid4()
    token = issue_grant(client, UUID(profile["id"]), run_id)
    fake = install_stream_transport(
        client,
        [b'data: {"choices":[{"delta":{"content":"not done"}}]}\n\n'],
    )
    response = client.post(
        "/internal/v1/model/chat/completions",
        headers=headers(token),
        json={
            "run_id": str(run_id),
            "model_id": "research-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 4,
        },
    )
    assert response.status_code == 200
    assert '"code":"provider_stream_incomplete"' in response.text
    assert "not done" in response.text
    assert "provider-secret" not in response.text
    assert fake.closed == 1


def test_stream_generator_close_closes_upstream(client: TestClient) -> None:
    profile = create_profile(client)
    run_id = uuid4()
    token = issue_grant(client, UUID(profile["id"]), run_id)
    fake = install_stream_transport(
        client,
        [
            b'data: {"choices":[{"delta":{"content":"x"}}]}\n\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n',
            b'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n',
            b"data: [DONE]\n\n",
        ],
    )
    app = app_for(client)
    user_id = UUID(client.get("/api/v1/users/me", headers=headers("owner")).json()["id"])
    session = app.state.session_factory()
    try:
        stream = cast(
            Any,
            stream_model(
                session,
                wrapper=app.state.credential_wrapper,
                token=token,
                run_id=run_id,
                model_id="research-model",
                messages=[{"role": "user", "content": "hello"}],
                max_output_tokens=4,
                transport=app.state.provider_transport,
                limits=app.state.gateway_limits,
            ),
        )
        next(stream)
        stream.close()
        assert fake.closed == 1
        del user_id
    finally:
        session.close()


def test_invalid_derived_grant_digest_rolls_back_and_bounds_input(client: TestClient) -> None:
    session = app_for(client).state.session_factory()
    try:
        with pytest.raises(GrantInvalid):
            exchange_run_grant_for_model(
                session, token="x" * 4097, run_id=uuid4(), model_id="research-model"
            )
        assert not session.in_transaction()
        with pytest.raises(GrantInvalid):
            exchange_run_grant_for_model(
                session, token="unknown", run_id=uuid4(), model_id="research-model"
            )
        assert not session.in_transaction()
    finally:
        session.close()


def test_stream_uses_configured_response_limit(client: TestClient) -> None:
    profile = create_profile(client)
    run_id = uuid4()
    token = issue_grant(client, UUID(profile["id"]), run_id)
    fake = install_stream_transport(client, [b"x" * 65])
    app = app_for(client)
    app.state.gateway_limits = replace(app.state.gateway_limits, max_response_bytes=64)
    response = client.post(
        "/internal/v1/model/chat/completions",
        headers=headers(token),
        json={
            "run_id": str(run_id),
            "model_id": "research-model",
            "messages": [{"role": "user", "content": "hello"}],
            "max_output_tokens": 4,
        },
    )
    assert response.status_code == 200
    assert '"code":"provider_response_too_large"' in response.text
    assert fake.closed == 1


@pytest.mark.parametrize("address", [("93.184.216.34", "127.0.0.1")])
def test_stream_transport_rejects_mixed_dns_before_open(address: tuple[str, str]) -> None:
    fake = FakeStreamTransport([])
    transport = ProviderTransport(
        resolver=lambda _host, _port: address,
        stream_transport=fake,
        retry_count=0,
    )
    with pytest.raises(ProviderTransportError, match="unsafe_base_url"):
        transport.open_stream(
            base_url="https://provider.example",
            api_key="secret",
            payload={"stream": True},
        )
    assert fake.opened == 0


def test_provider_stream_assembles_fragmented_tool_calls_without_provider_ids() -> None:
    frames = list(
        normalize_model_stream(
            [
                (
                    b'data: {"choices":[{"delta":{"tool_calls":['
                    b'{"id":"provider-secret","index":0,"function":{"name":"get_context"}}]}}]}\n\n'
                ),
                (
                    b'data: {"choices":[{"delta":{"tool_calls":['
                    b'{"index":0,"function":{"arguments":"{}"}}]},"finish_reason":"tool_calls"}]}\n\n'
                ),
                b'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n',
                b"data: [DONE]\n\n",
            ],
            max_output_tokens=4,
            limits=StreamLimits(max_response_bytes=10_000),
        )
    )
    deltas = [delta for frame in frames for delta in frame.tool_call_deltas]
    assert [(item.index, item.name, item.arguments) for item in deltas] == [
        (0, "get_context", None),
        (0, None, "{}"),
    ]
    assert all("provider" not in repr(frame) for frame in frames)

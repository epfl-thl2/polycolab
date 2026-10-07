"""ASGI chunk limits, including the actual registration application's ordering."""

import asyncio
import json
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from test_registration import ORIGIN, PASSWORD, _setup
from test_registration import open_client as open_client

from polycolab.accounts.ingress import RegistrationBodyLimitMiddleware


async def _request(
    app: ASGIApp,
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[list[Message], int]:
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/auth/register",
        "raw_path": b"/auth/register",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"registration.example"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", b"application/json"),
            *(headers or []),
        ],
        "server": ("registration.example", 443),
        "client": ("127.0.0.1", 1234),
    }
    replies: list[Message] = []
    completed = asyncio.Event()
    reads = 0

    async def receive() -> Message:
        nonlocal reads
        if reads == len(chunks):
            await completed.wait()
            return {"type": "http.disconnect"}
        chunk = chunks[reads]
        reads += 1
        return {"type": "http.request", "body": chunk, "more_body": reads < len(chunks)}

    async def send(message: Message) -> None:
        replies.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            completed.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=3)
    return replies, reads


async def _never(scope: Scope, receive: Receive, send: Send) -> None:
    raise AssertionError("rejected registration body reached application")


@pytest.mark.parametrize("length", [None, b"0", b"8"])
def test_actual_chunks_stop_at_limit_even_without_or_with_false_length(
    length: bytes | None,
) -> None:
    headers = [] if length is None else [(b"content-length", length)]
    replies, reads = asyncio.run(
        _request(
            RegistrationBodyLimitMiddleware(_never, max_bytes=8),
            [b"12345678", b"private", b"never-read"],
            headers=headers,
        )
    )
    assert reads == 2
    assert replies[0]["status"] == 413
    response_headers = dict(replies[0]["headers"])
    assert response_headers[b"cache-control"] == b"no-store"
    assert response_headers[b"referrer-policy"] == b"no-referrer"
    assert response_headers[b"x-content-type-options"] == b"nosniff"
    body = json.loads(replies[1]["body"])
    assert body["error"]["code"] == "registration_request_too_large"
    UUID(body["error"]["request_id"])
    assert b"private" not in replies[1]["body"]


@pytest.mark.parametrize("length,status", [(b"9", 413), (b"-1", 400), (b"bad", 400)])
def test_invalid_or_oversize_declaration_never_reads_body(length: bytes, status: int) -> None:
    replies, reads = asyncio.run(
        _request(
            RegistrationBodyLimitMiddleware(_never, max_bytes=8),
            [b"never-read"],
            headers=[(b"content-length", length)],
        )
    )
    assert reads == 0 and replies[0]["status"] == status


def test_duplicate_lengths_are_rejected() -> None:
    replies, reads = asyncio.run(
        _request(
            RegistrationBodyLimitMiddleware(_never, max_bytes=8),
            [b"never-read"],
            headers=[(b"content-length", b"0"), (b"content-length", b"8")],
        )
    )
    assert reads == 0 and replies[0]["status"] == 400


def test_exact_bound_replays_all_chunks_once() -> None:
    received: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        received.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})
        received.append(await receive())

    replies, reads = asyncio.run(
        _request(
            RegistrationBodyLimitMiddleware(app, max_bytes=8),
            [b"12", b"", b"345678"],
        )
    )
    assert reads == 3 and replies[0]["status"] == 204
    assert received == [
        {"type": "http.request", "body": b"12345678", "more_body": False},
        {"type": "http.disconnect"},
    ]


def test_disconnect_before_complete_never_calls_application() -> None:
    async def run() -> None:
        async def receive() -> Message:
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            raise AssertionError("disconnected request produced a response")

        await RegistrationBodyLimitMiddleware(_never, max_bytes=8)(
            {"type": "http", "method": "POST", "path": "/auth/register", "headers": []},
            receive,
            send,
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "scope",
    [
        {"type": "lifespan"},
        {"type": "websocket"},
        {"type": "http", "method": "GET", "path": "/auth/register"},
        {"type": "http", "method": "POST", "path": "/api/v1/workspaces/p/artifacts"},
    ],
)
def test_other_scopes_are_not_buffered(scope: Scope) -> None:
    async def run() -> None:
        async def receive() -> Message:
            raise AssertionError("unrelated scope was consumed")

        async def send(message: Message) -> None:
            pass

        async def app(actual: Scope, reader: Receive, writer: Send) -> None:
            assert actual is scope and reader is receive and writer is send

        await RegistrationBodyLimitMiddleware(app, max_bytes=8)(scope, receive, send)

    asyncio.run(run())


def test_real_application_stops_oversize_body_before_admission(
    open_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, open_client.app)

    def fail(*args: object) -> None:
        raise AssertionError("oversize body reached durable admission or password hash")

    monkeypatch.setattr("polycolab.app.application._enforce_registration_admission", fail)
    monkeypatch.setattr("polycolab.accounts.builtin.hash_password", fail)
    replies, reads = asyncio.run(
        _request(
            app,
            [b"x" * app.state.settings.registration_max_request_bytes, b"x", b"never-read"],
        )
    )
    assert reads == 2 and replies[0]["status"] == 413


def test_real_application_accepts_replayed_chunked_registration(open_client: TestClient) -> None:
    _setup(open_client)
    payload = json.dumps({"username": "chunked-user", "password": PASSWORD}).encode()
    replies, reads = asyncio.run(
        _request(cast(FastAPI, open_client.app), [payload[:10], payload[10:]])
    )
    assert reads == 2 and replies[0]["status"] == 201
    result = json.loads(b"".join(reply.get("body", b"") for reply in replies))
    assert result["authenticated"] is True and result["is_admin"] is False

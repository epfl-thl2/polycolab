"""Run-sequence replay must not skip late output from an earlier execution."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any, cast
from uuid import UUID

from fastapi.testclient import TestClient
from test_conversations_api import (
    create_connection,
    create_project,
    create_session,
    headers,
    interrupt,
    send,
)

from polycolab.agents.conversations import append_worker_event, finish_run
from polycolab.conversations.routes.router import _conversation_event_stream
from polycolab.entities.enums import AgentRunEventKind, AgentRunStatus


def test_later_cancellation_waits_for_preceding_output_before_advancing_cursor(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    conversation_id = str(create_session(client, project_id)["id"])
    provider_connection_id = str(create_connection(client, "owner")["id"])
    first = send(client, conversation_id, provider_connection_id).json()["run"]["id"]
    second = send(client, conversation_id, provider_connection_id).json()["run"]["id"]
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers={"Authorization": "Bearer polycolab-local-runtime-worker-token"},
        json={"worker_id": "replay-worker"},
    )
    assert claim.status_code == 200 and claim.json()["run_id"] == first
    generation = claim.json()["lease_generation"]
    assert interrupt(client, conversation_id, second).status_code == 202
    user_id = UUID(client.get("/api/v1/account", headers=headers("owner")).json()["id"])
    app = cast(Any, client.app)
    app.state.settings.runtime_sse_poll_seconds = 0.01
    with app.state.session_factory() as db:
        append_worker_event(
            db,
            run_id=UUID(first),
            worker_id="replay-worker",
            lease_generation=generation,
            idempotency_key="delta",
            kind=AgentRunEventKind.ASSISTANT_DELTA,
            payload={"text": "Partial"},
        )

    class Request:
        def __init__(self) -> None:
            self.app = app

        async def is_disconnected(self) -> bool:
            return False

    async def replay() -> None:
        stream = _conversation_event_stream(
            cast(Any, Request()),
            conversation_id=UUID(conversation_id),
            user_id=user_id,
            cursor=(0, 0),
        )
        frames = [await anext(stream), await anext(stream)]
        assert [frame.splitlines()[0] for frame in frames] == [b"id: 1:1", b"id: 1:2"]
        pending = asyncio.ensure_future(anext(stream))
        try:
            try:
                await asyncio.wait_for(asyncio.shield(pending), timeout=0.05)
                raise AssertionError("later cancellation overtook unfinished earlier output")
            except TimeoutError:
                pass
            with app.state.session_factory() as db:
                finish_run(
                    db,
                    run_id=UUID(first),
                    worker_id="replay-worker",
                    lease_generation=generation,
                    status=AgentRunStatus.COMPLETED,
                    final_message_md="Final answer",
                )
            frames.append(await asyncio.wait_for(pending, timeout=2))
            frames.extend([await anext(stream), await anext(stream), await anext(stream)])
            assert [frame.splitlines()[0] for frame in frames] == [
                b"id: 1:1",
                b"id: 1:2",
                b"id: 1:3",
                b"id: 1:4",
                b"id: 2:1",
                b"id: 2:2",
            ]
            assert b'"message_id"' in frames[2] and b"Final answer" not in frames[2]
        finally:
            if not pending.done():
                pending.cancel()
            await cast(AsyncGenerator[bytes], stream).aclose()
        client.patch(
            f"/api/v1/conversations/{conversation_id}",
            headers=headers("owner"),
            json={"archived": True},
        )
        resumed = [
            frame
            async for frame in _conversation_event_stream(
                cast(Any, Request()),
                conversation_id=UUID(conversation_id),
                user_id=user_id,
                cursor=(1, 3),
            )
        ]
        assert [frame.splitlines()[0] for frame in resumed] == [
            b"id: 1:4",
            b"id: 2:1",
            b"id: 2:2",
        ]

    asyncio.run(replay())


def test_diagnostic_failures_are_safe_in_metadata_transcript_and_replay(
    client: TestClient,
) -> None:
    project_id = str(create_project(client)["id"])
    conversation_id = str(create_session(client, project_id)["id"])
    provider_connection_id = str(create_connection(client, "owner")["id"])
    run_id = send(client, conversation_id, provider_connection_id).json()["run"]["id"]
    claim = client.post(
        "/internal/v1/runtime/claims",
        headers={"Authorization": "Bearer polycolab-local-runtime-worker-token"},
        json={"worker_id": "failure-worker"},
    )
    assert claim.status_code == 200
    with cast(Any, client.app).state.session_factory() as db:
        finish_run(
            db,
            run_id=UUID(run_id),
            worker_id="failure-worker",
            lease_generation=claim.json()["lease_generation"],
            status=AgentRunStatus.FAILED,
            failure_code="private diagnostic /token",
        )
    root = f"/api/v1/conversations/{conversation_id}"
    assert client.patch(root, headers=headers("owner"), json={"archived": True}).status_code == 200
    for path in (
        root,
        root + "/items",
        root + "/runs",
        root + "/stream",
        f"/api/v1/runs/{run_id}",
    ):
        response = client.get(path, headers=headers("owner"))
        assert response.status_code == 200
        assert "private diagnostic" not in response.text
        assert "execution_failed" in response.text

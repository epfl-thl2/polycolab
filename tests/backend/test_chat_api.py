"""Direct chat crosses the real API/SQLite boundary with a deterministic provider."""

import json
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_sessions_api import add_member, create_project, headers

from polycolab.db.models.chat import SqlChatConversation, SqlChatTurn
from polycolab.entities.time import utc_now
from polycolab.model_gateway.transport import ProviderStreamResponse, ProviderTransportError


class Provider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.closed = 0
        self.failure: str | None = None
        self.tools = False
        self.truncated = False
        self.before_reply: Any = None

    def open_stream(self, **kwargs: Any) -> ProviderStreamResponse:
        self.calls.append(kwargs)
        if self.before_reply:
            self.before_reply()
        if self.failure:
            raise ProviderTransportError(self.failure)
        frames: list[dict[str, Any]]
        if kwargs["responses"]:
            output = [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Remembered 42."}],
                }
            ]
            if self.tools:
                output = [{"type": "function_call", "name": "run_command"}]
            frames = [
                {
                    "type": "response.completed",
                    "response": {
                        "status": "completed",
                        "output": output,
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                }
            ]
        else:
            delta: dict[str, Any] = {"content": "Remembered 42."}
            if self.tools:
                delta = {
                    "tool_calls": [
                        {"index": 0, "function": {"name": "run_command", "arguments": "{}"}}
                    ]
                }
            frames = [
                {"choices": [{"delta": delta, "finish_reason": None}]},
                {
                    "choices": [
                        {"delta": {}, "finish_reason": "tool_calls" if self.tools else "stop"}
                    ]
                },
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            ]
        data = b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
        if not kwargs["responses"] and not self.truncated:
            data += b"data: [DONE]\n\n"
        if self.truncated:
            data = b'data: {"type":"response.created"}\n\n' if kwargs["responses"] else data[:-100]
        return ProviderStreamResponse(200, iter([data]), self.close)

    def close(self) -> None:
        self.closed += 1


def setup(
    client: TestClient, wire_api: str = "responses", project_id: str | None = None
) -> tuple[Provider, str, str]:
    app = cast(FastAPI, client.app)
    # Direct chat remains available with hosted execution disabled.
    app.state.settings.feature_agent_execution_enabled = False
    app.state.settings.runtime_codex_image = "unavailable-image"
    provider = Provider()
    app.state.provider_transport = provider
    profile = client.post(
        "/api/v1/gateway/profiles",
        headers=headers("owner"),
        json={
            "display_name": "Chat model",
            "wire_api": wire_api,
            "base_url": "https://8.8.8.8/v1",
            "model_id": "chat-model",
            "api_key": "sk-private-chat-test-key",
        },
    )
    assert profile.status_code == 201, profile.text
    conversation = client.post(
        "/api/v1/chat/conversations",
        headers=headers("owner"),
        json={"title": "Remember a number", "project_id": project_id},
    )
    assert conversation.status_code == 201, conversation.text
    return provider, profile.json()["id"], conversation.json()["id"]


def send(
    client: TestClient,
    conversation: str,
    profile: str,
    content: str = "Remember 42.",
    request_id: str | None = None,
    token: str = "owner",
) -> Any:
    return client.post(
        f"/api/v1/chat/conversations/{conversation}/turns",
        headers=headers(token),
        json={
            "profile_id": profile,
            "request_id": request_id or str(uuid4()),
            "content_md": content,
        },
    )


@pytest.mark.parametrize("wire_api", ["responses", "chat_completions"])
def test_chat_round_trip_history_retry_and_protocol(client: TestClient, wire_api: str) -> None:
    provider, profile, conversation = setup(client, wire_api)
    key = str(uuid4())
    first = send(client, conversation, profile, request_id=key)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "completed"
    assert first.json()["response_md"] == "Remembered 42."
    assert send(client, conversation, profile, request_id=key).json() == first.json()
    assert len(provider.calls) == 1
    assert send(client, conversation, profile, "Different", key).status_code == 409
    second = send(client, conversation, profile, "What number?")
    assert second.json()["status"] == "completed", second.text
    payload = provider.calls[-1]["payload"]
    assert payload["input" if wire_api == "responses" else "messages"] == [
        {"role": "user", "content": "Remember 42."},
        {"role": "assistant", "content": "Remembered 42."},
        {"role": "user", "content": "What number?"},
    ]
    assert "tools" not in payload and "tool_choice" not in payload
    assert provider.calls[-1]["responses"] == (wire_api == "responses")
    if wire_api == "responses":
        assert payload["store"] is False
    assert provider.closed == 2
    history = client.get(
        f"/api/v1/chat/conversations/{conversation}/turns", headers=headers("owner")
    )
    assert [turn["sequence"] for turn in history.json()] == [1, 2]
    assert "sk-private" not in history.text
    listed = client.get("/api/v1/chat/conversations", headers=headers("owner")).json()
    assert listed[0]["id"] == conversation


@pytest.mark.parametrize("wire_api", ["responses", "chat_completions"])
@pytest.mark.parametrize("problem", ["failure", "tools", "truncated"])
def test_failed_turns_are_durable_and_never_replayed(
    client: TestClient, wire_api: str, problem: str
) -> None:
    provider, profile, conversation = setup(client, wire_api)
    setattr(provider, problem, "provider_request_uncertain" if problem == "failure" else True)
    key = str(uuid4())
    result = send(client, conversation, profile, request_id=key)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "failed"
    assert result.json()["response_md"] is None
    assert send(client, conversation, profile, request_id=key).json() == result.json()
    assert len(provider.calls) == 1
    provider.failure = None
    provider.tools = provider.truncated = False
    next_turn = send(client, conversation, profile, "Try a new question.")
    assert next_turn.json()["status"] == "completed"
    assert provider.calls[-1]["payload"]["input" if wire_api == "responses" else "messages"] == [
        {"role": "user", "content": "Try a new question."}
    ]


def test_chat_privacy_project_access_and_profile_ownership(client: TestClient) -> None:
    project = str(create_project(client)["id"])
    add_member(client, project, "contributor", "CONTRIBUTOR")
    provider, profile, conversation = setup(client, project_id=project)
    for token in ("outsider", "contributor"):
        assert (
            client.get(
                f"/api/v1/chat/conversations/{conversation}/turns", headers=headers(token)
            ).status_code
            == 404
        )
        assert send(client, conversation, profile, token=token).status_code == 404
    assert (
        client.get(
            "/api/v1/chat/conversations",
            headers=headers("contributor"),
            params={"project_id": project},
        ).json()
        == []
    )
    assert client.get("/api/v1/chat/conversations").status_code == 401
    assert client.get("/api/v1/chat/conversations", headers=headers("owner")).json() == []
    private_profile = client.post(
        "/api/v1/gateway/profiles",
        headers=headers("outsider"),
        json={
            "display_name": "Other",
            "base_url": "https://8.8.8.8/v1",
            "model_id": "other",
            "api_key": "other-secret",
        },
    ).json()["id"]
    assert send(client, conversation, private_profile).status_code == 404
    assert provider.calls == []
    assert send(client, conversation, profile, "  ").status_code == 422
    cast(FastAPI, client.app).state.settings.execution_user_daily_tokens = 1
    assert send(client, conversation, profile).status_code == 429
    assert provider.calls == []


def test_concurrent_retry_busy_and_interrupted_recovery(client: TestClient) -> None:
    provider, profile, conversation = setup(client)
    key = str(uuid4())

    def in_flight() -> None:
        retry = send(client, conversation, profile, request_id=key)
        assert retry.json()["status"] == "pending"
        assert send(client, conversation, profile, "Parallel question").status_code == 409

    provider.before_reply = in_flight
    completed = send(client, conversation, profile, request_id=key)
    assert completed.json()["status"] == "completed", completed.text
    assert len(provider.calls) == 1
    app = cast(FastAPI, client.app)
    with app.state.session_factory() as db:
        parent = db.get(SqlChatConversation, UUID(conversation))
        parent.active_until = utc_now() - timedelta(seconds=1)
        parent.active_request_id = UUID(key)
        turn = db.get(SqlChatTurn, UUID(completed.json()["id"]))
        turn.status, turn.response_md = "pending", None
        db.commit()
    recovered = client.get(
        f"/api/v1/chat/conversations/{conversation}/turns", headers=headers("owner")
    ).json()
    assert recovered[0]["status"] == "failed"
    assert recovered[0]["failure_code"] == "chat_request_interrupted"


def test_saved_retry_is_available_after_rate_budget_is_exhausted(client: TestClient) -> None:
    provider, profile, conversation = setup(client)
    cast(FastAPI, client.app).state.settings.execution_user_requests_per_minute = 1
    key = str(uuid4())
    original = send(client, conversation, profile, request_id=key)
    assert original.status_code == 200
    assert send(client, conversation, profile, request_id=key).json() == original.json()
    assert send(client, conversation, profile, "New request").status_code == 429
    assert len(provider.calls) == 1

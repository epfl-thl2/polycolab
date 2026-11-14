"""The transport projection cannot expose private prompts or execution context."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError

from polycolab.conversations.routes.presenters import item_read, session_read
from polycolab.conversations.routes.schemas import SessionCapabilities, SessionEvent
from polycolab.entities.conversation import (
    AgentAuthor,
    AgentConfiguration,
    Conversation,
    ConversationHierarchy,
    ConversationItem,
    ConversationItemData,
    ConversationOrigin,
    ItemVisibility,
    ToolAuthor,
    ToolCallData,
    ToolResultData,
)


def test_public_transcript_retains_attribution_and_omits_sensitive_tool_content() -> None:
    agent_id = uuid4()
    call: ConversationItem[ConversationItemData] = ConversationItem(
        id=uuid4(),
        conversation_id=uuid4(),
        sequence=1,
        author=AgentAuthor(agent_id, "Pinned agent"),
        created_at=datetime.now(UTC),
        data=ToolCallData("call-1", "get_context", '{"private": "arguments"}'),
    )
    projected = item_read(call).model_dump(mode="json")
    assert projected["type"] == "tool_call"
    assert projected["author"]["agent_version_id"] == str(agent_id)
    assert projected["author"]["display_name"] == "Pinned agent"
    assert projected["data"]["arguments_json"] is None
    result = replace(
        call,
        author=ToolAuthor("get_context", agent_id),
        data=ToolResultData("call-1", "get_context", "ok", '{"private": "result"}'),
    )
    assert item_read(result).model_dump()["data"]["output_json"] is None
    with pytest.raises(ValueError, match="model-only"):
        item_read(replace(call, visibility=ItemVisibility.MODEL_ONLY))


def test_configuration_is_complete_and_private_prompt_only_reaches_owner() -> None:
    session_id, owner_id, viewer_id = uuid4(), uuid4(), uuid4()
    configuration = AgentConfiguration(
        agent_version_id=uuid4(),
        display_name="Pinned",
        agent_kind="CUSTOM",
        agent_version=5,
        harness="codex",
        harness_version=None,
        connection_protocol=None,
        system_prompt_override="Private instructions",
    )
    value = Conversation(
        id=session_id,
        owner_id=owner_id,
        project_id=uuid4(),
        title=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        hierarchy=ConversationHierarchy(root_id=session_id),
        origin=ConversationOrigin.AGENT,
        configuration=configuration,
    )
    capabilities = SessionCapabilities(
        can_send=False, can_manage=False, can_share=False, can_stream=True
    )
    owner = session_read(
        value, viewer_id=owner_id, capabilities=capabilities, latest_execution=None
    )
    reader = session_read(
        value, viewer_id=viewer_id, capabilities=capabilities, latest_execution=None
    )
    assert owner.configuration is not None and reader.configuration is not None
    assert owner.configuration.system_prompt_override == "Private instructions"
    assert reader.configuration.system_prompt_override is None
    assert reader.configuration.agent_version_id == configuration.agent_version_id
    assert reader.configuration.harness_version is None
    assert reader.usage is None and reader.latest_execution is None
    assert "runtime" not in reader.model_dump()


def test_human_event_schema_cannot_supply_runtime_outputs_or_authorship() -> None:
    adapter: TypeAdapter[SessionEvent] = TypeAdapter(SessionEvent)
    message = {
        "type": "message",
        "client_request_id": str(uuid4()),
        "content_md": "Hello",
        "provider_profile_id": str(uuid4()),
    }
    assert adapter.validate_python(message).type == "message"
    for override in (
        {"type": "assistant"},
        {"author_user_id": str(uuid4())},
        {"agent_version_id": str(uuid4())},
        {"role": "AGENT"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python({**message, **override})
    interrupt = adapter.validate_python({"type": "interrupt", "run_id": str(uuid4())})
    assert interrupt.type == "interrupt"

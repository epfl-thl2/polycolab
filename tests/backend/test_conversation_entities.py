"""Materialization preserves authorship and scope without loading ORM state lazily."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from polycolab.db.converters.conversation import (
    agent_message,
    conversation,
    legacy_execution,
)
from polycolab.db.models.agents import (
    SqlConversation,
    SqlConversationConfiguration,
    SqlConversationItem,
)
from polycolab.db.models.conversations import SqlLegacyConversationExecution
from polycolab.entities.conversation import (
    ConversationKind,
    ConversationStatus,
    MessageRole,
)
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentSessionStatus,
)


def test_conversation_sources_preserve_owner_and_project() -> None:
    owner, project = uuid4(), uuid4()
    now = datetime(2026, 10, 30)
    direct = conversation(
        SqlConversation(
            id=uuid4(),
            created_by_user_id=owner,
            project_id=project,
            title="Direct",
            created_at=now,
            updated_at=now,
            origin="legacy_direct",
            status=AgentSessionStatus.ACTIVE,
        ),
        None,
    )
    identity = uuid4()
    configuration = SqlConversationConfiguration(
        conversation_id=identity,
        agent_version_id=uuid4(),
        agent_kind="RESEARCHER",
        agent_version=1,
        agent_display_name="Researcher",
        harness="platform",
    )
    agent = conversation(
        SqlConversation(
            id=identity,
            created_by_user_id=owner,
            configuration=configuration,
            project_id=project,
            title=None,
            created_at=now,
            updated_at=now,
            archived_at=now,
            status=AgentSessionStatus.ARCHIVED,
            is_shared=True,
        ),
        configuration,
    )
    assert direct.owner_id == agent.owner_id == owner
    assert direct.project_id == agent.project_id == project
    assert direct.kind is ConversationKind.DIRECT
    assert direct.status is ConversationStatus.ACTIVE
    assert direct.is_shared is False
    assert agent.kind is ConversationKind.AGENT
    assert agent.status is ConversationStatus.ARCHIVED
    assert agent.is_shared is True
    assert agent.title is None
    assert agent.archived_at == now.replace(tzinfo=UTC)
    assert direct.created_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (AgentMessageRole.USER, MessageRole.USER),
        (AgentMessageRole.AGENT, MessageRole.ASSISTANT),
        (AgentMessageRole.SYSTEM, MessageRole.SYSTEM),
    ],
)
def test_message_preserves_identity_and_role(role: AgentMessageRole, expected: MessageRole) -> None:
    author = uuid4() if role is AgentMessageRole.USER else None
    row = SqlConversationItem(
        id=uuid4(),
        session_id=uuid4(),
        sequence=5,
        role=role,
        author_user_id=author,
        content_md="Saved **message**",
        created_at=datetime.now(UTC),
    )
    item = agent_message(row)
    assert item.id == row.id
    assert item.conversation_id == row.session_id
    assert item.sequence == 5
    assert item.author_user_id == author
    assert item.type == "message"
    assert item.data.role is expected
    row.content_md = "Changed ORM row"
    assert item.data.content_md == "Saved **message**"


def test_unknown_persisted_turn_status_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown historical execution status"):
        legacy_execution(SqlLegacyConversationExecution(status="unknown"))


def test_complete_configuration_is_materialized_without_runtime_state() -> None:
    from dataclasses import asdict

    now = datetime.now(UTC)
    identity = uuid4()
    configuration = SqlConversationConfiguration(
        conversation_id=identity,
        agent_version_id=uuid4(),
        agent_kind="RESEARCHER",
        agent_version=2,
        agent_display_name="Researcher",
        harness="codex",
        system_prompt="Private instructions",
    )
    worktree = uuid4()
    row = SqlConversation(
        id=identity,
        created_by_user_id=uuid4(),
        project_id=uuid4(),
        configuration=configuration,
        task_id=worktree,
        created_at=now,
        updated_at=now,
        status=AgentSessionStatus.ACTIVE,
        is_shared=False,
    )
    value = conversation(row, configuration)
    assert value.configuration is not None
    assert value.configuration.agent_version_id == configuration.agent_version_id
    assert value.configuration.display_name == "Researcher"
    assert value.configuration.agent_version == 2
    assert value.configuration.agent_kind == "RESEARCHER"
    assert value.configuration.harness == "codex"
    assert value.configuration.harness_version is None
    assert value.configuration.connection_protocol is None
    assert value.configuration.system_prompt_override == "Private instructions"
    assert value.working_context.worktree_id == worktree
    assert value.hierarchy.root_id == row.id
    assert value.hierarchy.parent_id is None
    assert value.latest_execution is None
    assert value.usage is None
    assert "items" not in asdict(value)
    assert "runtime_binding" not in asdict(value)
    configuration.system_prompt = "Changed prompt"
    configuration.agent_display_name = "Changed agent"
    assert value.configuration.display_name == "Researcher"
    assert value.configuration.system_prompt_override == "Private instructions"
    configuration.conversation_id = uuid4()
    with pytest.raises(ValueError, match="different conversation"):
        conversation(row, configuration)


def test_agent_authorship_and_execution_attribution_are_explicit() -> None:
    from polycolab.entities.conversation import AgentAuthor

    agent_id, run_id = uuid4(), uuid4()
    row = SqlConversationItem(
        id=uuid4(),
        session_id=uuid4(),
        sequence=2,
        role=AgentMessageRole.AGENT,
        content_md="Answer",
        created_at=datetime.now(UTC),
    )
    historical = agent_message(row)
    assert historical.author == AgentAuthor(None)
    assert historical.execution_id is None
    attributed = agent_message(
        row,
        agent_version_id=agent_id,
        agent_display_name="Researcher",
        execution_id=run_id,
    )
    assert attributed.author == AgentAuthor(agent_id, "Researcher")
    assert attributed.execution_id == run_id
    assert attributed.author_user_id is None


def test_unattributed_human_message_is_rejected() -> None:
    with pytest.raises(ValueError, match="attributable authorship"):
        agent_message(SqlConversationItem(role=AgentMessageRole.USER, author_user_id=None))


def test_hierarchy_and_legacy_configuration_invariants() -> None:
    from dataclasses import replace

    from polycolab.entities.conversation import (
        Conversation,
        ConversationHierarchy,
        ConversationOrigin,
        ConversationSharing,
    )

    conversation_id = uuid4()
    root = Conversation(
        id=conversation_id,
        owner_id=uuid4(),
        project_id=uuid4(),
        title=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        hierarchy=ConversationHierarchy(root_id=conversation_id),
    )
    with pytest.raises(ValueError, match="reference themselves"):
        replace(root, hierarchy=ConversationHierarchy(root_id=uuid4()))
    with pytest.raises(ValueError, match="own parent or root"):
        replace(root, hierarchy=ConversationHierarchy(root_id=root.id, parent_id=uuid4()))
    child = replace(
        root,
        id=uuid4(),
        hierarchy=ConversationHierarchy(root_id=root.id, parent_id=root.id),
    )
    assert child.sharing is ConversationSharing.PRIVATE
    with pytest.raises(ValueError, match="standalone"):
        replace(root, project_id=None, sharing=ConversationSharing.PROJECT_READABLE)
    with pytest.raises(ValueError, match="legacy direct"):
        replace(
            root,
            origin=ConversationOrigin.LEGACY_DIRECT,
            sharing=ConversationSharing.PROJECT_CONTRIBUTABLE,
        )
    with pytest.raises(ValueError, match="spawning context"):
        ConversationHierarchy(root_id=root.id, spawning_run_id=uuid4())


def test_payload_authorship_and_item_state_invariants() -> None:
    from dataclasses import FrozenInstanceError, replace

    from polycolab.entities.conversation import (
        AgentAuthor,
        ConversationItem,
        ErrorData,
        ItemStatus,
        ItemVisibility,
        ToolAuthor,
        ToolCallData,
        ToolResultData,
    )

    call = ConversationItem(
        id=uuid4(),
        conversation_id=uuid4(),
        sequence=1,
        author=AgentAuthor(uuid4()),
        data=ToolCallData(call_id="call-1", name="search"),
        created_at=datetime.now(UTC),
        status=ItemStatus.INTERRUPTED,
        visibility=ItemVisibility.MODEL_ONLY,
    )
    assert call.type == "tool_call"
    assert call.data.arguments_json is None
    with pytest.raises(FrozenInstanceError):
        call.sequence = 9  # type: ignore[misc]
    with pytest.raises(ValueError, match="positive"):
        replace(call, sequence=0)
    with pytest.raises(ValueError, match="agent authored"):
        replace(call, author=ToolAuthor("search"))
    result = ConversationItem(
        id=uuid4(),
        conversation_id=call.conversation_id,
        sequence=2,
        author=ToolAuthor("search"),
        data=ToolResultData(call_id="call-1", name="search", outcome="completed"),
        created_at=datetime.now(UTC),
    )
    assert result.type == "tool_result"
    assert result.data.output_json is None
    with pytest.raises(ValueError, match="tool author"):
        replace(result, author=ToolAuthor("another-tool"))
    with pytest.raises(ValueError, match="safe code"):
        ErrorData("Private provider diagnostic: secret")


def test_usage_keeps_unknowns_and_reservations_distinct() -> None:
    from polycolab.db.converters.conversation import token_observation
    from polycolab.db.models.agents import SqlAgentRunUsage
    from polycolab.entities.conversation import (
        TokenObservation,
        UsageReservation,
        UsageSummary,
    )
    from polycolab.entities.enums import UsageSource

    run_id = uuid4()
    observation = token_observation(
        SqlAgentRunUsage(
            run_id=run_id,
            source=UsageSource.UNKNOWN,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            observed_at=datetime(2026, 10, 30),
        )
    )
    summary = UsageSummary((observation,), (UsageReservation(tokens=5000, cost_microusd=100),))
    assert summary.observations[0].input_tokens is None
    assert summary.observations[0].total_tokens is None
    assert summary.observations[0].execution_id == run_id
    assert summary.observations[0].observed_at == datetime(2026, 10, 30, tzinfo=UTC)
    assert summary.reservations[0].tokens == 5000
    with pytest.raises(ValueError, match="non-negative"):
        TokenObservation(source=UsageSource.ESTIMATED, input_tokens=-1)
    with pytest.raises(ValueError, match="provenance"):
        TokenObservation(source=UsageSource.UNKNOWN, event_cursor=1)


def test_execution_and_private_runtime_materialization() -> None:
    from dataclasses import asdict

    from polycolab.db.converters.conversation import (
        execution_summary,
        private_runtime_binding,
    )
    from polycolab.db.models.agents import SqlAgentRun, SqlRuntimeSessionBinding
    from polycolab.entities.enums import AgentRunStatus, RuntimeBindingStatus

    now = datetime(2026, 10, 30)
    execution = execution_summary(
        SqlAgentRun(
            id=uuid4(),
            status=AgentRunStatus.COMPLETED,
            gateway_model_id="requested-model",
            created_at=now,
            started_at=now,
            finished_at=now,
        )
    )
    assert execution.requested_model == "requested-model"
    assert execution.observed_model is None
    assert execution.created_at.tzinfo is UTC
    binding = private_runtime_binding(
        SqlRuntimeSessionBinding(
            id=uuid4(),
            session_id=uuid4(),
            adapter_name="codex",
            opaque_runtime_ref="private-reference",
            status=RuntimeBindingStatus.SUPERSEDED,
            created_at=now,
            ended_at=now,
        )
    )
    assert binding.external_session_reference == "private-reference"
    assert binding.ended_at == now.replace(tzinfo=UTC)
    assert "external_session_reference" not in asdict(execution)

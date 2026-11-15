"""Explicit materialization of conversation values from persisted history."""

from typing import Literal, cast
from uuid import UUID, uuid5

from polycolab.db.converters.time import timestamp
from polycolab.db.models.agents import (
    SqlAgentRun,
    SqlAgentRunUsage,
    SqlConversation,
    SqlConversationConfiguration,
    SqlConversationItem,
    SqlRuntimeSessionBinding,
)
from polycolab.db.models.conversations import SqlLegacyConversationExecution
from polycolab.entities.conversation import (
    AgentAuthor,
    AgentConfiguration,
    Conversation,
    ConversationExecution,
    ConversationHierarchy,
    ConversationItem,
    ConversationItemData,
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
    ErrorData,
    ExecutionContext,
    ExecutionSummary,
    HumanAuthor,
    ItemAuthor,
    ItemStatus,
    ItemVisibility,
    LegacyExecution,
    MessageData,
    MessageRole,
    PrivateRuntimeBinding,
    SystemAuthor,
    TokenObservation,
    ToolAuthor,
    ToolCallData,
    ToolResultData,
    UsageReservation,
    UsageSummary,
    WorkingContext,
    safe_failure_code,
)
from polycolab.entities.enums import (
    AgentMessageRole,
    AgentRunStatus,
    AgentSessionStatus,
    UsageSource,
)


def conversation(
    row: SqlConversation, configuration: SqlConversationConfiguration | None
) -> Conversation:
    if configuration is not None and configuration.conversation_id != row.id:
        raise ValueError("agent configuration belongs to a different conversation")
    return Conversation(
        id=row.id,
        hierarchy=ConversationHierarchy(
            root_id=row.root_id or row.id,
            parent_id=row.parent_id,
            spawning_run_id=row.spawning_run_id,
            spawning_item_id=row.spawning_item_id,
            delegated_task=row.delegated_task,
        ),
        owner_id=row.created_by_user_id,
        project_id=row.project_id,
        title=row.title,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
        origin=ConversationOrigin(row.origin or "agent"),
        configuration=AgentConfiguration(
            agent_version_id=configuration.agent_version_id,
            display_name=configuration.agent_display_name,
            agent_kind=configuration.agent_kind,
            agent_version=configuration.agent_version,
            harness=configuration.harness,
            harness_version=configuration.harness_version,
            connection_protocol=configuration.connection_protocol,
            system_prompt_override=configuration.system_prompt,
        )
        if configuration is not None
        else None,
        working_context=WorkingContext(worktree_id=row.worktree_id),
        status=(
            ConversationStatus.ARCHIVED
            if row.status == AgentSessionStatus.ARCHIVED
            else ConversationStatus.ACTIVE
        ),
        sharing=ConversationSharing(row.sharing or "private"),
        archived_at=timestamp(row.archived_at),
    )


def agent_message(
    row: SqlConversationItem,
    *,
    agent_version_id: UUID | None = None,
    agent_display_name: str | None = None,
    execution_id: UUID | None = None,
) -> ConversationItem[MessageData]:
    if row.role is AgentMessageRole.USER and row.author_user_id is None:
        raise ValueError("human messages require attributable authorship")
    author = (
        HumanAuthor(row.author_user_id)
        if row.role is AgentMessageRole.USER and row.author_user_id is not None
        else AgentAuthor(agent_version_id, agent_display_name)
        if row.role is AgentMessageRole.AGENT
        else SystemAuthor()
    )
    return ConversationItem(
        id=row.id,
        conversation_id=row.session_id,
        sequence=row.sequence,
        author=author,
        execution_id=execution_id,
        status=ItemStatus(row.status or "completed"),
        visibility=ItemVisibility(row.visibility or "user_visible"),
        data=MessageData(
            role={
                AgentMessageRole.USER: MessageRole.USER,
                AgentMessageRole.AGENT: MessageRole.ASSISTANT,
                AgentMessageRole.SYSTEM: MessageRole.SYSTEM,
            }[row.role],
            content_md=row.content_md,
        ),
        created_at=timestamp(row.created_at),
    )


def legacy_execution(row: SqlLegacyConversationExecution) -> LegacyExecution:
    if row.status not in {"completed", "failed", "interrupted"}:
        raise ValueError("unknown historical execution status")
    return LegacyExecution(
        id=row.id,
        conversation_id=row.conversation_id,
        request_id=row.request_id,
        sequence=row.sequence,
        provider_connection_id=row.provider_connection_id,
        model_id=row.model_id,
        status=cast("Literal['completed', 'failed', 'interrupted']", row.status),
        failure_code=safe_failure_code(row.failure_code) if row.failure_code is not None else None,
        created_at=timestamp(row.created_at),
        usage=UsageSummary(
            observations=(
                TokenObservation(
                    source=UsageSource.PROVIDER_REPORTED
                    if row.input_tokens is not None or row.output_tokens is not None
                    else UsageSource.UNKNOWN,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    execution_id=row.id,
                ),
            ),
            reservations=(UsageReservation(row.reserved_tokens, row.reserved_cost_microusd),),
        ),
    )


def execution_summary(row: SqlAgentRun) -> ExecutionSummary:
    return ExecutionSummary(
        id=row.id,
        status=row.status,
        requested_model=row.gateway_model_id,
        observed_model=None,
        created_at=timestamp(row.created_at),
        started_at=timestamp(row.started_at),
        finished_at=timestamp(row.finished_at),
        failure_code=safe_failure_code(row.failure_code) if row.failure_code is not None else None,
    )


def execution(row: SqlAgentRun, *, usage: UsageSummary | None = None) -> ConversationExecution:
    return ConversationExecution(
        conversation_id=row.session_id,
        project_id=row.project_id,
        requested_by_user_id=row.requested_by_user_id,
        request_id=row.client_request_id,
        request_item_id=row.request_message_id,
        parent_run_id=row.parent_run_id,
        sequence=row.queue_sequence,
        origin=ConversationOrigin.AGENT,
        summary=execution_summary(row),
        attempt=row.attempt,
        cancel_requested_at=timestamp(row.cancel_requested_at),
        deadline_at=timestamp(row.deadline_at),
        updated_at=timestamp(row.updated_at),
        context=ExecutionContext(
            artifact_ids=tuple(UUID(value) for value in row.requested_context_artifact_ids),
        ),
        usage=usage,
    )


def legacy_execution_record(
    row: SqlLegacyConversationExecution, *, owner_id: UUID, project_id: UUID | None
) -> ConversationExecution:
    historical = legacy_execution(row)
    return ConversationExecution(
        conversation_id=historical.conversation_id,
        project_id=project_id,
        requested_by_user_id=owner_id,
        request_id=historical.request_id,
        request_item_id=uuid5(historical.id, "conversation-human"),
        parent_run_id=None,
        sequence=historical.sequence,
        origin=ConversationOrigin.LEGACY_DIRECT,
        summary=ExecutionSummary(
            id=historical.id,
            status="INTERRUPTED"
            if historical.status == "interrupted"
            else AgentRunStatus(historical.status.upper()),
            requested_model=historical.model_id,
            observed_model=None,
            created_at=historical.created_at,
            started_at=None,
            finished_at=None,
            failure_code=historical.failure_code,
        ),
        attempt=None,
        cancel_requested_at=None,
        deadline_at=None,
        updated_at=None,
        context=None,
        usage=historical.usage,
    )


def token_observation(row: SqlAgentRunUsage) -> TokenObservation:
    return TokenObservation(
        source=row.source,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        observed_at=timestamp(row.observed_at),
        execution_id=row.run_id,
        event_cursor=row.event_cursor,
    )


def private_runtime_binding(row: SqlRuntimeSessionBinding) -> PrivateRuntimeBinding:
    return PrivateRuntimeBinding(
        id=row.id,
        conversation_id=row.session_id,
        adapter=row.adapter_name,
        external_session_reference=row.opaque_runtime_ref,
        status=row.status,
        created_at=timestamp(row.created_at),
        ended_at=timestamp(row.ended_at),
    )


def conversation_item(row: SqlConversationItem) -> ConversationItem[ConversationItemData]:
    """Materialize a typed payload without following ORM relationships."""
    if row.item_type == "message":
        return cast(
            ConversationItem[ConversationItemData],
            agent_message(
                row, agent_version_id=row.agent_version_id, execution_id=row.execution_id
            ),
        )
    payload = row.payload or {}
    data: ConversationItemData
    author: ItemAuthor
    if row.item_type == "tool_call":
        data = ToolCallData(
            call_id=_optional_text(payload, "call_id"),
            name=_required_text(payload, "name"),
            arguments_json=_optional_text(payload, "arguments_json"),
        )
        author = AgentAuthor(row.agent_version_id)
    elif row.item_type == "tool_result":
        data = ToolResultData(
            call_id=_optional_text(payload, "call_id"),
            name=_required_text(payload, "name"),
            outcome=_required_text(payload, "outcome"),
            output_json=_optional_text(payload, "output_json"),
        )
        author = ToolAuthor(data.name, row.agent_version_id)
    elif row.item_type == "error":
        data = ErrorData(code=safe_failure_code(_required_text(payload, "code")))
        author = SystemAuthor()
    else:
        raise ValueError("unknown persisted conversation item type")
    return ConversationItem(
        id=row.id,
        conversation_id=row.session_id,
        sequence=row.sequence,
        author=author,
        data=data,
        created_at=timestamp(row.created_at),
        execution_id=row.execution_id,
        status=ItemStatus(row.status),
        visibility=ItemVisibility(row.visibility),
    )


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError("invalid stored item field")
    return value


def _required_text(payload: dict[str, object], key: str) -> str:
    value = _optional_text(payload, key)
    if value is None:
        raise ValueError("missing stored item field")
    return value

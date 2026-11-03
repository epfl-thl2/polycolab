"""Explicit public projections over materialized values; no database access."""

from uuid import UUID

from polycolab.conversations.routes.schemas import (
    AgentAuthorRead,
    AgentConfigurationRead,
    ErrorItemRead,
    ErrorPayloadRead,
    ExecutionSummaryRead,
    HierarchyRead,
    HumanAuthorRead,
    ItemAuthorRead,
    ItemRead,
    MessageItemRead,
    MessagePayloadRead,
    RunRead,
    SessionCapabilities,
    SessionRead,
    SystemAuthorRead,
    ToolAuthorRead,
    ToolCallItemRead,
    ToolCallPayloadRead,
    ToolResultItemRead,
    ToolResultPayloadRead,
    TranscriptItem,
    UsageRead,
    WorkingContextRead,
)
from polycolab.entities.conversation import (
    AgentAuthor,
    Conversation,
    ConversationExecution,
    ConversationItem,
    ConversationItemData,
    ErrorData,
    HumanAuthor,
    ItemAuthor,
    ItemVisibility,
    MessageData,
    SystemAuthor,
    ToolAuthor,
    ToolCallData,
    ToolResultData,
)
from polycolab.entities.enums import AgentRunStatus

TERMINAL = {
    AgentRunStatus.COMPLETED,
    AgentRunStatus.CANCELLED,
    AgentRunStatus.FAILED,
    AgentRunStatus.TIMED_OUT,
    "INTERRUPTED",
}


def execution_summary_read(
    value: ConversationExecution, *, viewer_id: UUID, owner_id: UUID
) -> ExecutionSummaryRead:
    summary = value.summary
    return ExecutionSummaryRead(
        id=summary.id,
        status=summary.status,
        requested_model=summary.requested_model,
        observed_model=summary.observed_model,
        created_at=summary.created_at,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        failure_code=summary.failure_code,
        cancel_requested_at=value.cancel_requested_at,
        requested_by_user_id=value.requested_by_user_id,
        can_interrupt=(
            summary.status not in TERMINAL and viewer_id in {owner_id, value.requested_by_user_id}
        ),
    )


def run_read(
    value: ConversationExecution, *, viewer_id: UUID, owner_id: UUID, can_send: bool
) -> RunRead:
    summary = execution_summary_read(value, viewer_id=viewer_id, owner_id=owner_id)
    return RunRead(
        **summary.model_dump(),
        session_id=value.conversation_id,
        project_id=value.project_id,
        origin=value.origin,
        client_request_id=value.request_id,
        request_item_id=value.request_item_id,
        parent_run_id=value.parent_run_id,
        queue_sequence=value.sequence,
        attempt=value.attempt,
        deadline_at=value.deadline_at,
        updated_at=value.updated_at,
        usage=UsageRead.model_validate(value.usage) if value.usage is not None else None,
        can_resume=(
            can_send
            and value.origin.value == "agent"
            and value.requested_by_user_id == viewer_id
            and summary.status in TERMINAL
        ),
        can_read_private_context=(
            value.origin.value == "agent" and value.requested_by_user_id == viewer_id
        ),
    )


def session_read(
    value: Conversation,
    *,
    viewer_id: UUID,
    capabilities: SessionCapabilities,
    latest_execution: ConversationExecution | None,
) -> SessionRead:
    configuration = (
        AgentConfigurationRead.model_validate(value.configuration)
        if value.configuration is not None
        else None
    )
    if configuration is not None and viewer_id != value.owner_id:
        configuration = configuration.model_copy(update={"system_prompt_override": None})
    return SessionRead(
        id=value.id,
        owner_id=value.owner_id,
        project_id=value.project_id,
        title=value.title,
        origin=value.origin,
        status=value.status,
        sharing=value.sharing,
        configuration=configuration,
        working_context=WorkingContextRead.model_validate(value.working_context),
        hierarchy=HierarchyRead.model_validate(value.hierarchy),
        created_at=value.created_at,
        updated_at=value.updated_at,
        archived_at=value.archived_at,
        capabilities=capabilities,
        latest_execution=execution_summary_read(
            latest_execution, viewer_id=viewer_id, owner_id=value.owner_id
        )
        if latest_execution is not None
        else None,
        usage=UsageRead.model_validate(value.usage) if value.usage is not None else None,
    )


def author_read(value: ItemAuthor) -> ItemAuthorRead:
    match value:
        case HumanAuthor():
            return HumanAuthorRead(user_id=value.user_id)
        case AgentAuthor():
            return AgentAuthorRead(
                agent_version_id=value.agent_version_id, display_name=value.display_name
            )
        case ToolAuthor():
            return ToolAuthorRead(name=value.name, agent_version_id=value.agent_version_id)
        case SystemAuthor():
            return SystemAuthorRead()
    raise TypeError("unsupported transcript author")


def item_read(value: ConversationItem[ConversationItemData]) -> TranscriptItem:
    """The share preview and readers receive the same visible transcript projection.

    Raw tool arguments and outputs are private execution context. They never
    enter this public projection, including when a historical record has them.
    """
    if value.visibility is not ItemVisibility.USER_VISIBLE:
        raise ValueError("model-only context is not a public transcript item")
    base = ItemRead(
        id=value.id,
        session_id=value.conversation_id,
        sequence=value.sequence,
        author=author_read(value.author),
        execution_id=value.execution_id,
        created_at=value.created_at,
        status=value.status,
    ).model_dump()
    match value.data:
        case MessageData() as data:
            return MessageItemRead(**base, data=MessagePayloadRead.model_validate(data))
        case ToolCallData() as data:
            return ToolCallItemRead(
                **base,
                data=ToolCallPayloadRead(call_id=data.call_id, name=data.name, arguments_json=None),
            )
        case ToolResultData() as data:
            return ToolResultItemRead(
                **base,
                data=ToolResultPayloadRead(
                    call_id=data.call_id, name=data.name, outcome=data.outcome, output_json=None
                ),
            )
        case ErrorData() as data:
            return ErrorItemRead(**base, data=ErrorPayloadRead(code=data.code))
    raise TypeError("unsupported transcript payload")

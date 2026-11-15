"""Atomic transcript allocation and materialized conversation reads."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from polycolab.db.converters.conversation import (
    conversation as materialize_conversation,
)
from polycolab.db.converters.conversation import (
    conversation_item,
    legacy_execution,
    legacy_execution_record,
    token_observation,
)
from polycolab.db.converters.conversation import (
    execution as materialize_execution,
)
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import (
    SqlAgentRunUsage,
    SqlExecutionJob,
    SqlMembership,
    SqlProject,
    SqlWorktree,
)
from polycolab.db.models.agents import (
    SqlAgentRun,
    SqlConversation,
    SqlConversationConfiguration,
    SqlConversationItem,
    SqlPlatformAgentVersion,
)
from polycolab.db.models.conversations import SqlLegacyConversationExecution
from polycolab.entities.conversation import (
    AgentAuthor,
    Conversation,
    ConversationExecution,
    ConversationItem,
    ConversationItemData,
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
    HumanAuthor,
    ItemAuthor,
    ItemStatus,
    ItemVisibility,
    LegacyExecution,
    MessageData,
    ToolAuthor,
    UsageReservation,
    UsageSummary,
)
from polycolab.entities.enums import AgentMessageRole, StoredConversationStatus


class SqlConversationStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    @persistence_boundary
    def items(
        self,
        conversation_id: UUID,
        *,
        after: int = 0,
        limit: int = 100,
        include_model_context: bool = False,
    ) -> list[ConversationItem[ConversationItemData]]:
        if after < 0 or not 1 <= limit <= 101:
            raise ValueError("invalid transcript page")
        query = select(SqlConversationItem).where(
            SqlConversationItem.conversation_id == conversation_id,
            SqlConversationItem.sequence > after,
        )
        if not include_model_context:
            query = query.where(SqlConversationItem.visibility == "user_visible")
        return [
            conversation_item(row)
            for row in self._session.scalars(
                query.order_by(SqlConversationItem.sequence).limit(limit)
            )
        ]

    @persistence_boundary
    def append_item(
        self,
        conversation_id: UUID,
        *,
        item_id: UUID,
        author: ItemAuthor,
        data: ConversationItemData,
        created_at: datetime,
        execution_id: UUID | None = None,
        status: ItemStatus = ItemStatus.COMPLETED,
        visibility: ItemVisibility = ItemVisibility.USER_VISIBLE,
    ) -> ConversationItem[ConversationItemData]:
        # Validation happens before allocating a sequence. The single UPDATE
        # serializes appends on PostgreSQL and SQLite within the caller's transaction.
        draft = ConversationItem(
            id=item_id,
            conversation_id=conversation_id,
            sequence=1,
            author=author,
            data=data,
            created_at=created_at,
            execution_id=execution_id,
            status=status,
            visibility=visibility,
        )
        parent = self._session.get(SqlConversation, conversation_id)
        if parent is None or parent.origin != "agent":
            raise ValueError("only agent conversations accept new items")
        if execution_id is not None:
            run = self._session.get(SqlAgentRun, execution_id)
            if run is None or run.conversation_id != conversation_id:
                raise ValueError("execution belongs to another conversation")
        sequence = self._session.scalar(
            update(SqlConversation)
            .where(SqlConversation.id == conversation_id)
            .values(next_message_sequence=SqlConversation.next_message_sequence + 1)
            .returning(SqlConversation.next_message_sequence)
        )
        if sequence is None:
            raise ValueError("conversation not found")
        row = SqlConversationItem(
            id=item_id,
            conversation_id=conversation_id,
            sequence=sequence,
            author_user_id=author.user_id if isinstance(author, HumanAuthor) else None,
            agent_version_id=author.agent_version_id
            if isinstance(author, (AgentAuthor, ToolAuthor))
            else None,
            role=(
                AgentMessageRole.USER
                if isinstance(author, HumanAuthor)
                else AgentMessageRole.AGENT
                if isinstance(author, AgentAuthor)
                else AgentMessageRole.SYSTEM
            ),
            content_md=data.content_md if isinstance(data, MessageData) else "",
            item_type=draft.type,
            payload=None if isinstance(data, MessageData) else asdict(data),
            execution_id=execution_id,
            created_at=created_at,
            status=status.value,
            visibility=visibility.value,
        )
        self._session.add(row)
        self._session.flush()
        return conversation_item(row)

    @persistence_boundary
    def conversation(
        self, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation | None:
        query = select(SqlConversation).where(SqlConversation.id == conversation_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self._session.scalar(query)
        return materialize_conversation(row, row.configuration) if row is not None else None

    @persistence_boundary
    def list_accessible(
        self,
        user_id: UUID,
        *,
        project_id: UUID | None = None,
        origin: ConversationOrigin | None = None,
        archived: bool | None = None,
        parent_id: UUID | None = None,
        after: tuple[datetime, UUID] | None = None,
        limit: int = 100,
    ) -> list[Conversation]:
        if not 1 <= limit <= 101:
            raise ValueError("invalid conversation page")
        member = (
            select(SqlMembership.id)
            .where(
                SqlMembership.project_id == SqlConversation.project_id,
                SqlMembership.user_id == user_id,
                SqlProject.id == SqlConversation.project_id,
                SqlProject.deleted_at.is_(None),
            )
            .exists()
        )
        query = select(SqlConversation).where(
            or_(SqlConversation.project_id.is_(None), member),
            or_(
                SqlConversation.created_by_user_id == user_id, SqlConversation.sharing != "private"
            ),
        )
        if project_id is not None:
            query = query.where(SqlConversation.project_id == project_id)
        if parent_id is not None:
            query = query.where(SqlConversation.parent_id == parent_id)
        if origin is not None:
            query = query.where(SqlConversation.origin == origin.value)
        if archived is not None:
            query = query.where(
                SqlConversation.status
                == (
                    StoredConversationStatus.ARCHIVED
                    if archived
                    else StoredConversationStatus.ACTIVE
                )
            )
        if after is not None:
            query = query.where(
                or_(
                    SqlConversation.updated_at < after[0],
                    (SqlConversation.updated_at == after[0]) & (SqlConversation.id < after[1]),
                )
            )
        return [
            materialize_conversation(row, row.configuration)
            for row in self._session.scalars(
                query.order_by(SqlConversation.updated_at.desc(), SqlConversation.id.desc()).limit(
                    limit
                )
            )
        ]

    @persistence_boundary
    def create(self, value: Conversation) -> Conversation:
        if (
            value.origin is not ConversationOrigin.AGENT
            or value.project_id is None
            or value.configuration is None
        ):
            raise ValueError("new conversations require a project and agent configuration")
        hierarchy = value.hierarchy
        if hierarchy.parent_id is not None:
            parent = self.conversation(hierarchy.parent_id, for_update=True)
            if (
                parent is None
                or parent.project_id != value.project_id
                or parent.hierarchy.root_id != hierarchy.root_id
            ):
                raise ValueError("child must belong to its parent's project and root tree")
            if hierarchy.spawning_run_id is not None:
                run = self._session.get(SqlAgentRun, hierarchy.spawning_run_id)
                if run is None or run.conversation_id != parent.id:
                    raise ValueError("spawning run must belong to the parent")
            if hierarchy.spawning_item_id is not None:
                item = self._session.get(SqlConversationItem, hierarchy.spawning_item_id)
                if item is None or item.conversation_id != parent.id:
                    raise ValueError("spawning item must belong to the parent")
        if value.working_context.worktree_id is not None:
            task = self._session.get(SqlWorktree, value.working_context.worktree_id)
            if task is None or task.project_id != value.project_id:
                raise ValueError("worktree must belong to the conversation project")
        config = value.configuration
        agent = self._session.get(SqlPlatformAgentVersion, config.agent_version_id)
        if agent is None or (agent.display_name, agent.agent_kind.value, agent.version) != (
            config.display_name,
            config.agent_kind,
            config.agent_version,
        ):
            raise ValueError("configuration must preserve pinned agent identity")
        row = SqlConversation(
            id=value.id,
            created_by_user_id=value.owner_id,
            project_id=value.project_id,
            title=value.title,
            origin=value.origin.value,
            sharing=value.sharing.value,
            root_id=hierarchy.root_id,
            parent_id=hierarchy.parent_id,
            spawning_run_id=hierarchy.spawning_run_id,
            spawning_item_id=hierarchy.spawning_item_id,
            delegated_task=hierarchy.delegated_task,
            worktree_id=value.working_context.worktree_id,
            created_at=value.created_at,
            updated_at=value.updated_at,
            archived_at=value.archived_at,
            status=StoredConversationStatus(value.status.value.upper()),
            configuration=SqlConversationConfiguration(
                agent_version_id=config.agent_version_id,
                agent_display_name=config.display_name,
                agent_kind=config.agent_kind,
                agent_version=config.agent_version,
                harness=config.harness,
                harness_version=config.harness_version,
                connection_protocol=config.connection_protocol,
                system_prompt=config.system_prompt_override,
            ),
        )
        self._session.add(row)
        self._session.flush()
        return materialize_conversation(row, row.configuration)

    @persistence_boundary
    def set_metadata(
        self,
        conversation_id: UUID,
        *,
        title: str | None,
        status: ConversationStatus,
        updated_at: datetime,
    ) -> Conversation:
        row = self._session.scalar(
            select(SqlConversation).where(SqlConversation.id == conversation_id).with_for_update()
        )
        if row is None:
            raise ValueError("conversation not found")
        row.title = title
        row.status = StoredConversationStatus(status.value.upper())
        row.archived_at = (
            (row.archived_at or updated_at) if status is ConversationStatus.ARCHIVED else None
        )
        row.updated_at = updated_at
        self._session.flush()
        return materialize_conversation(row, row.configuration)

    @persistence_boundary
    def set_sharing(
        self,
        conversation_id: UUID,
        sharing: ConversationSharing,
        *,
        updated_at: datetime,
    ) -> Conversation:
        row = self._session.scalar(
            select(SqlConversation).where(SqlConversation.id == conversation_id).with_for_update()
        )
        if row is None:
            raise ValueError("conversation not found")
        if sharing is not ConversationSharing.PRIVATE and (
            row.origin != "agent" or row.project_id is None
        ):
            raise ValueError("legacy or standalone history cannot be shared")
        row.sharing = sharing.value
        row.updated_at = updated_at
        self._session.flush()
        return materialize_conversation(row, row.configuration)

    @persistence_boundary
    def legacy_runs(
        self, conversation_id: UUID, *, after: int = 0, limit: int = 100
    ) -> list[LegacyExecution]:
        if after < 0 or not 1 <= limit <= 101:
            raise ValueError("invalid execution page")
        return [
            legacy_execution(row)
            for row in self._session.scalars(
                select(SqlLegacyConversationExecution)
                .where(
                    SqlLegacyConversationExecution.conversation_id == conversation_id,
                    SqlLegacyConversationExecution.sequence > after,
                )
                .order_by(SqlLegacyConversationExecution.sequence)
                .limit(limit)
            )
        ]

    def _usage(self, run_id: UUID) -> UsageSummary:
        observations = tuple(
            token_observation(row)
            for row in self._session.scalars(
                select(SqlAgentRunUsage)
                .where(SqlAgentRunUsage.run_id == run_id)
                .order_by(SqlAgentRunUsage.event_cursor)
            )
        )
        reservation = self._session.scalar(
            select(SqlExecutionJob).where(SqlExecutionJob.agent_run_id == run_id)
        )
        return UsageSummary(
            observations=observations,
            reservations=(
                UsageReservation(
                    reservation.agent_model_tokens, reservation.agent_provider_cost_microusd
                ),
            )
            if reservation is not None
            and reservation.agent_model_tokens is not None
            and reservation.agent_provider_cost_microusd is not None
            else (),
        )

    @persistence_boundary
    def execution(self, execution_id: UUID) -> ConversationExecution | None:
        row = self._session.get(SqlAgentRun, execution_id)
        if row is not None:
            return materialize_execution(row, usage=self._usage(row.id))
        historical = self._session.get(SqlLegacyConversationExecution, execution_id)
        if historical is None:
            return None
        parent = self._session.get(SqlConversation, historical.conversation_id)
        if parent is None:
            raise ValueError("execution has no conversation")
        return legacy_execution_record(
            historical, owner_id=parent.created_by_user_id, project_id=parent.project_id
        )

    @persistence_boundary
    def executions(
        self, conversation_id: UUID, *, after: int = 0, limit: int = 100
    ) -> list[ConversationExecution]:
        if after < 0 or not 1 <= limit <= 101:
            raise ValueError("invalid execution page")
        parent = self._session.get(SqlConversation, conversation_id)
        if parent is None:
            return []
        if parent.origin == "legacy_direct":
            return [
                legacy_execution_record(
                    row, owner_id=parent.created_by_user_id, project_id=parent.project_id
                )
                for row in self._session.scalars(
                    select(SqlLegacyConversationExecution)
                    .where(
                        SqlLegacyConversationExecution.conversation_id == conversation_id,
                        SqlLegacyConversationExecution.sequence > after,
                    )
                    .order_by(SqlLegacyConversationExecution.sequence)
                    .limit(limit)
                )
            ]
        return [
            materialize_execution(row)
            for row in self._session.scalars(
                select(SqlAgentRun)
                .where(
                    SqlAgentRun.conversation_id == conversation_id,
                    SqlAgentRun.queue_sequence > after,
                )
                .order_by(SqlAgentRun.queue_sequence)
                .limit(limit)
            )
        ]

    @persistence_boundary
    def latest_executions(self, conversation_ids: list[UUID]) -> dict[UUID, ConversationExecution]:
        if not conversation_ids:
            return {}
        ranked = (
            select(
                SqlAgentRun.id,
                func.row_number()
                .over(
                    partition_by=SqlAgentRun.conversation_id,
                    order_by=SqlAgentRun.queue_sequence.desc(),
                )
                .label("position"),
            )
            .where(SqlAgentRun.conversation_id.in_(conversation_ids))
            .subquery()
        )
        result = {
            row.conversation_id: materialize_execution(row)
            for row in self._session.scalars(
                select(SqlAgentRun)
                .join(ranked, ranked.c.id == SqlAgentRun.id)
                .where(ranked.c.position == 1)
            )
        }
        historical = (
            select(
                SqlLegacyConversationExecution.id,
                func.row_number()
                .over(
                    partition_by=SqlLegacyConversationExecution.conversation_id,
                    order_by=SqlLegacyConversationExecution.sequence.desc(),
                )
                .label("position"),
            )
            .where(SqlLegacyConversationExecution.conversation_id.in_(conversation_ids))
            .subquery()
        )
        for execution_row, parent in self._session.execute(
            select(SqlLegacyConversationExecution, SqlConversation)
            .join(
                SqlConversation,
                SqlConversation.id == SqlLegacyConversationExecution.conversation_id,
            )
            .join(historical, historical.c.id == SqlLegacyConversationExecution.id)
            .where(historical.c.position == 1)
        ):
            result[parent.id] = legacy_execution_record(
                execution_row, owner_id=parent.created_by_user_id, project_id=parent.project_id
            )
        return result

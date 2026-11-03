"""Materialized transcript operations; the caller owns transaction completion."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from polycolab.entities.conversation import (
    Conversation,
    ConversationExecution,
    ConversationItem,
    ConversationItemData,
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
    ItemAuthor,
    ItemStatus,
    ItemVisibility,
    LegacyExecution,
)


class ConversationStore(Protocol):
    def items(
        self,
        conversation_id: UUID,
        *,
        after: int = 0,
        limit: int = 100,
        include_model_context: bool = False,
    ) -> list[ConversationItem[ConversationItemData]]: ...

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
    ) -> ConversationItem[ConversationItemData]: ...

    def conversation(
        self, conversation_id: UUID, *, for_update: bool = False
    ) -> Conversation | None: ...
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
    ) -> list[Conversation]: ...
    def create(self, value: Conversation) -> Conversation: ...
    def set_metadata(
        self,
        conversation_id: UUID,
        *,
        title: str | None,
        status: ConversationStatus,
        updated_at: datetime,
    ) -> Conversation: ...
    def set_sharing(
        self, conversation_id: UUID, sharing: ConversationSharing, *, updated_at: datetime
    ) -> Conversation: ...
    def legacy_runs(
        self, conversation_id: UUID, *, after: int = 0, limit: int = 100
    ) -> list[LegacyExecution]: ...
    def execution(self, execution_id: UUID) -> ConversationExecution | None: ...
    def executions(
        self, conversation_id: UUID, *, after: int = 0, limit: int = 100
    ) -> list[ConversationExecution]: ...
    def latest_executions(
        self, conversation_ids: list[UUID]
    ) -> dict[UUID, ConversationExecution]: ...

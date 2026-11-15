"""Conversation access policy independent of HTTP schemas and database adapters."""

from datetime import datetime
from uuid import UUID

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectNotFound,
    project_policy,
)
from polycolab.entities.conversation import (
    Conversation,
    ConversationOrigin,
    ConversationSharing,
    ConversationStatus,
)
from polycolab.entities.time import utc_now
from polycolab.transaction import Transaction


class ConversationStateError(Exception):
    pass


def can_execute(transaction: Transaction, conversation_id: UUID, user_id: UUID) -> bool:
    """Recheck the sender's current conversation and project authority at worker boundaries."""
    value = transaction.conversations.conversation(conversation_id)
    return bool(
        value is not None
        and value.origin is ConversationOrigin.AGENT
        and value.status is ConversationStatus.ACTIVE
        and value.project_id is not None
        and (
            value.owner_id == user_id
            or value.sharing is ConversationSharing.MEMBERS_CAN_PARTICIPATE
        )
        and project_policy.can(transaction, value.project_id, user_id, ProjectAction.RUN_AGENTS)
    )


def require_read(transaction: Transaction, conversation_id: UUID, user_id: UUID) -> Conversation:
    value = transaction.conversations.conversation(conversation_id)
    if value is None:
        raise ProjectNotFound
    if value.owner_id != user_id and value.sharing is ConversationSharing.PRIVATE:
        raise ProjectNotFound
    if value.project_id is not None:
        project_policy.require_scope(transaction, value.project_id, user_id, ProjectAction.VIEW)
    elif value.owner_id != user_id:
        raise ProjectNotFound
    return value


def require_submit(transaction: Transaction, conversation_id: UUID, user_id: UUID) -> Conversation:
    value = require_read(transaction, conversation_id, user_id)
    if (
        value.origin is not ConversationOrigin.AGENT
        or value.status is not ConversationStatus.ACTIVE
        or value.project_id is None
    ):
        raise ConversationStateError("conversation is read-only")
    if (
        value.owner_id != user_id
        and value.sharing is not ConversationSharing.MEMBERS_CAN_PARTICIPATE
    ):
        raise AuthorizationDenied
    project_policy.require_scope(transaction, value.project_id, user_id, ProjectAction.RUN_AGENTS)
    return value


def require_owner(transaction: Transaction, conversation_id: UUID, user_id: UUID) -> Conversation:
    value = require_read(transaction, conversation_id, user_id)
    if value.owner_id != user_id:
        raise AuthorizationDenied
    return value


def require_interrupt(
    transaction: Transaction,
    conversation_id: UUID,
    user_id: UUID,
    *,
    requested_by_user_id: UUID,
) -> Conversation:
    value = require_read(transaction, conversation_id, user_id)
    if value.origin is not ConversationOrigin.AGENT:
        raise ConversationStateError("legacy history is read-only")
    if user_id not in {value.owner_id, requested_by_user_id}:
        raise AuthorizationDenied
    return value


def set_sharing(
    transaction: Transaction,
    conversation_id: UUID,
    user_id: UUID,
    sharing: ConversationSharing,
) -> Conversation:
    value = require_owner(transaction, conversation_id, user_id)
    if (
        value.origin is ConversationOrigin.LEGACY_DIRECT
        and sharing is not ConversationSharing.PRIVATE
    ):
        raise ConversationStateError("legacy history cannot be shared")
    result = transaction.conversations.set_sharing(conversation_id, sharing, updated_at=utc_now())
    transaction.commit()
    return result


def children(
    transaction: Transaction,
    conversation_id: UUID,
    user_id: UUID,
    *,
    after: tuple[datetime, UUID] | None = None,
    limit: int = 100,
) -> list[Conversation]:
    require_read(transaction, conversation_id, user_id)
    return transaction.conversations.list_accessible(
        user_id, parent_id=conversation_id, after=after, limit=limit
    )

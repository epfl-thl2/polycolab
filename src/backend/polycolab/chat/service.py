"""Chat authorization, ordered history, and retry identity."""

from datetime import timedelta
from uuid import UUID, uuid4

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.chat.store import ChatStore
from polycolab.entities.chat import ChatConversation, ChatTurn
from polycolab.entities.time import utc_now
from polycolab.transaction import Transaction


class ChatNotFound(Exception):
    pass


class ChatConflict(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_project(
    tx: Transaction, project_id: UUID | None, user_id: UUID, *, write: bool
) -> None:
    if project_id is not None:
        project_policy.require_scope(
            tx, project_id, user_id, ProjectAction.RUN_AGENTS if write else ProjectAction.VIEW
        )


def require_conversation(
    tx: Transaction, store: ChatStore, conversation_id: UUID, user_id: UUID, *, write: bool = False
) -> ChatConversation:
    conversation = store.conversation(conversation_id, user_id)
    if conversation is None:
        raise ChatNotFound
    require_project(tx, conversation.project_id, user_id, write=write)
    return conversation


def prior_turn(
    store: ChatStore, conversation_id: UUID, request_id: UUID, profile_id: UUID, content: str
) -> ChatTurn | None:
    existing = next(
        (turn for turn in store.turns(conversation_id) if turn.request_id == request_id), None
    )
    if existing and (existing.profile_id != profile_id or existing.content_md != content):
        raise ChatConflict("chat_retry_conflict")
    return existing


def messages_for_turn(
    store: ChatStore, conversation_id: UUID, content: str
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for turn in store.turns(conversation_id):
        if turn.status == "completed":
            messages.extend(
                [
                    {"role": "user", "content": turn.content_md},
                    {"role": "assistant", "content": turn.response_md},
                ]
            )
    messages.append({"role": "user", "content": content})
    return messages


def begin_turn(
    store: ChatStore,
    conversation_id: UUID,
    request_id: UUID,
    profile_id: UUID,
    model_id: str,
    content: str,
    reserved_tokens: int,
    reserved_cost: int,
    timeout: float,
) -> ChatTurn:
    sequence = store.claim(conversation_id, request_id, utc_now() + timedelta(seconds=timeout))
    if sequence is None:
        raise ChatConflict("chat_busy")
    return store.append(
        ChatTurn(
            id=uuid4(),
            conversation_id=conversation_id,
            request_id=request_id,
            sequence=sequence,
            profile_id=profile_id,
            model_id=model_id,
            content_md=content,
            response_md=None,
            status="pending",
            failure_code=None,
            input_tokens=None,
            output_tokens=None,
            created_at=utc_now(),
        ),
        reserved_tokens,
        reserved_cost,
    )

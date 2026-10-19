"""Human-authenticated, creator-private provider chat."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, field_validator

from polycolab.app.dependencies import CurrentUser, DbSession, Page, paginated
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.chat import service
from polycolab.db.stores.chat import SqlChatStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.chat import ChatConversation
from polycolab.entities.time import utc_now
from polycolab.execution.limits import (
    ExecutionLimitExceeded,
    enforce_chat_rate_limit,
    lock_chat_admission,
)
from polycolab.model_gateway.chat import complete_chat, prepare_chat
from polycolab.model_gateway.service import GatewayNotFound, ProviderFailure

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatConversationCreate(RequestModel):
    project_id: UUID | None = None
    title: str = Field(default="New chat", min_length=1, max_length=200)


class ChatConversationRead(ApiModel):
    id: UUID
    project_id: UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatTurnCreate(RequestModel):
    request_id: UUID
    profile_id: UUID
    content_md: str = Field(min_length=1, max_length=100_000)

    @field_validator("content_md")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must contain text")
        return value


class ChatTurnRead(ApiModel):
    id: UUID
    conversation_id: UUID
    request_id: UUID
    sequence: int
    profile_id: UUID
    model_id: str
    content_md: str
    response_md: str | None
    status: Literal["pending", "completed", "failed"]
    failure_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


def _conversation(
    db: DbSession, conversation_id: UUID, user_id: UUID, *, write: bool = False
) -> ChatConversation:
    try:
        return service.require_conversation(
            SqlAlchemyTransaction(db), SqlChatStore(db), conversation_id, user_id, write=write
        )
    except service.ChatNotFound:
        raise HTTPException(404, "not_found") from None


@router.post(
    "/conversations",
    response_model=ChatConversationRead,
    status_code=201,
    operation_id="createChatConversation",
)
def create_conversation(
    payload: ChatConversationCreate, db: DbSession, user: CurrentUser
) -> ChatConversationRead:
    service.require_project(SqlAlchemyTransaction(db), payload.project_id, user.id, write=True)
    conversation = SqlChatStore(db).create(user.id, payload.project_id, payload.title)
    db.commit()
    return ChatConversationRead.model_validate(conversation)


@router.get(
    "/conversations",
    response_model=list[ChatConversationRead],
    operation_id="listChatConversations",
)
def list_conversations(
    response: Response, page: Page, db: DbSession, user: CurrentUser, project_id: UUID | None = None
) -> list[ChatConversationRead]:
    service.require_project(SqlAlchemyTransaction(db), project_id, user.id, write=False)
    return paginated(
        [
            ChatConversationRead.model_validate(item)
            for item in SqlChatStore(db).conversations(user.id, project_id)
        ],
        page,
        response,
    )


@router.get(
    "/conversations/{conversation_id}/turns",
    response_model=list[ChatTurnRead],
    operation_id="listChatTurns",
)
def list_turns(
    conversation_id: UUID, response: Response, page: Page, db: DbSession, user: CurrentUser
) -> list[ChatTurnRead]:
    _conversation(db, conversation_id, user.id)
    SqlChatStore(db).recover_expired(conversation_id)
    db.commit()
    return paginated(
        [ChatTurnRead.model_validate(item) for item in SqlChatStore(db).turns(conversation_id)],
        page,
        response,
    )


@router.post(
    "/conversations/{conversation_id}/turns",
    response_model=ChatTurnRead,
    operation_id="sendChatTurn",
)
def send_turn(
    conversation_id: UUID,
    payload: ChatTurnCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ChatTurnRead:
    conversation = _conversation(db, conversation_id, user.id, write=True)
    store = SqlChatStore(db)
    settings = request.app.state.settings
    limits = request.app.state.gateway_limits
    timeout = settings.gateway_request_timeout_seconds
    try:
        # Serialize same-user retries before reading their durable identity.
        lock_chat_admission(db, user_id=user.id, project_id=conversation.project_id)
        store.recover_expired(conversation_id)
        existing = service.prior_turn(
            store, conversation_id, payload.request_id, payload.profile_id, payload.content_md
        )
        if existing:
            db.commit()
            return ChatTurnRead.model_validate(existing)
        enforce_chat_rate_limit(
            db,
            user_id=user.id,
            project_id=conversation.project_id,
            user_limit=settings.execution_user_requests_per_minute,
            project_limit=settings.execution_project_requests_per_minute,
            now=utc_now(),
        )
        messages = service.messages_for_turn(store, conversation_id, payload.content_md)
        model_request = prepare_chat(
            db, user_id=user.id, profile_id=payload.profile_id, messages=messages, limits=limits
        )
        budgets: list[tuple[UUID | None, int, int]] = [
            (
                None,
                settings.execution_user_daily_tokens,
                settings.execution_user_daily_cost_microusd,
            )
        ]
        if conversation.project_id is not None:
            budgets.append(
                (
                    conversation.project_id,
                    settings.execution_project_daily_tokens,
                    settings.execution_project_daily_cost_microusd,
                )
            )
        for project_id, token_limit, cost_limit in budgets:
            tokens, cost = store.daily_reservations(user.id, project_id)
            if (token_limit and tokens + model_request.reserved_tokens > token_limit) or (
                cost_limit and cost + model_request.reserved_cost > cost_limit
            ):
                raise ExecutionLimitExceeded("chat_daily_budget_exhausted", retry_after_seconds=60)
        turn = service.begin_turn(
            store,
            conversation_id,
            payload.request_id,
            payload.profile_id,
            model_request.model_id,
            payload.content_md,
            model_request.reserved_tokens,
            model_request.reserved_cost,
            timeout + settings.gateway_request_timeout_seconds + 30,
        )
        db.commit()
    except service.ChatConflict as exc:
        db.rollback()
        raise HTTPException(409, exc.code) from None
    except GatewayNotFound:
        db.rollback()
        raise HTTPException(404, "not_found") from None
    except ProviderFailure as exc:
        db.rollback()
        raise HTTPException(422, exc.code) from None
    except Exception:
        db.rollback()
        raise
    # The admission transaction is closed before credential-service or provider I/O.
    try:
        completion = complete_chat(
            model_request,
            wrapper=request.app.state.credential_wrapper,
            transport=request.app.state.provider_transport,
            limits=limits,
            timeout=timeout,
        )
        result = store.finish(
            turn.id, completion.text, None, completion.input_tokens, completion.output_tokens
        )
    except ProviderFailure as exc:
        result = store.finish(turn.id, None, exc.code, None, None)
    db.commit()
    return ChatTurnRead.model_validate(result)

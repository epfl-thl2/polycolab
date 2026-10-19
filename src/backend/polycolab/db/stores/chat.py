"""SQL persistence and atomic turn admission for private chat."""

from dataclasses import fields
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from polycolab.db.models.chat import SqlChatConversation, SqlChatTurn
from polycolab.entities.chat import ChatConversation, ChatTurn
from polycolab.entities.time import utc_now


def _conversation(row: SqlChatConversation) -> ChatConversation:
    return ChatConversation(
        **{field.name: getattr(row, field.name) for field in fields(ChatConversation)}
    )


def _turn(row: SqlChatTurn) -> ChatTurn:
    return ChatTurn(**{field.name: getattr(row, field.name) for field in fields(ChatTurn)})


class SqlChatStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def conversation(self, conversation_id: UUID, user_id: UUID) -> ChatConversation | None:
        row = self.session.scalar(
            select(SqlChatConversation).where(
                SqlChatConversation.id == conversation_id,
                SqlChatConversation.user_id == user_id,
            )
        )
        return _conversation(row) if row else None

    def conversations(self, user_id: UUID, project_id: UUID | None) -> list[ChatConversation]:
        return [
            _conversation(row)
            for row in self.session.scalars(
                select(SqlChatConversation)
                .where(
                    SqlChatConversation.user_id == user_id,
                    SqlChatConversation.project_id == project_id,
                )
                .order_by(SqlChatConversation.updated_at.desc(), SqlChatConversation.id)
            )
        ]

    def create(self, user_id: UUID, project_id: UUID | None, title: str) -> ChatConversation:
        row = SqlChatConversation(user_id=user_id, project_id=project_id, title=title)
        self.session.add(row)
        self.session.flush()
        return _conversation(row)

    def recover_expired(self, conversation_id: UUID) -> None:
        expired = self.session.scalar(
            update(SqlChatConversation)
            .where(
                SqlChatConversation.id == conversation_id,
                SqlChatConversation.active_until < utc_now(),
            )
            .values(active_request_id=None, active_until=None)
            .returning(SqlChatConversation.id)
        )
        if expired is not None:
            self.session.execute(
                update(SqlChatTurn)
                .where(
                    SqlChatTurn.conversation_id == conversation_id,
                    SqlChatTurn.status == "pending",
                )
                .values(status="failed", failure_code="chat_request_interrupted")
            )

    def turns(self, conversation_id: UUID) -> list[ChatTurn]:
        return [
            _turn(row)
            for row in self.session.scalars(
                select(SqlChatTurn)
                .where(SqlChatTurn.conversation_id == conversation_id)
                .order_by(SqlChatTurn.sequence)
            )
        ]

    def claim(self, conversation_id: UUID, request_id: UUID, until: datetime) -> int | None:
        now = utc_now()
        sequence = self.session.scalar(
            update(SqlChatConversation)
            .where(
                SqlChatConversation.id == conversation_id,
                or_(
                    SqlChatConversation.active_until.is_(None),
                    SqlChatConversation.active_until < now,
                ),
            )
            .values(
                sequence=SqlChatConversation.sequence + 1,
                active_request_id=request_id,
                active_until=until,
                updated_at=now,
            )
            .returning(SqlChatConversation.sequence)
        )
        if sequence is not None:
            self.session.execute(
                update(SqlChatTurn)
                .where(
                    SqlChatTurn.conversation_id == conversation_id,
                    SqlChatTurn.status == "pending",
                )
                .values(status="failed", failure_code="chat_request_interrupted")
            )
        return sequence

    def append(self, turn: ChatTurn, reserved_tokens: int, reserved_cost: int) -> ChatTurn:
        row = SqlChatTurn(
            **{field.name: getattr(turn, field.name) for field in fields(ChatTurn)},
            reserved_tokens=reserved_tokens,
            reserved_cost_microusd=reserved_cost,
        )
        self.session.add(row)
        self.session.flush()
        return _turn(row)

    def finish(
        self,
        turn_id: UUID,
        response: str | None,
        failure: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> ChatTurn:
        self.session.execute(
            update(SqlChatTurn)
            .where(
                SqlChatTurn.id == turn_id,
                SqlChatTurn.status == "pending",
            )
            .values(
                status="failed" if failure else "completed",
                response_md=response,
                failure_code=failure,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )
        row = cast(SqlChatTurn, self.session.get(SqlChatTurn, turn_id, populate_existing=True))
        self.session.execute(
            update(SqlChatConversation)
            .where(
                SqlChatConversation.id == row.conversation_id,
                SqlChatConversation.active_request_id == row.request_id,
            )
            .values(active_request_id=None, active_until=None, updated_at=utc_now())
        )
        return _turn(row)

    def daily_reservations(self, user_id: UUID, project_id: UUID | None) -> tuple[int, int]:
        since = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
        condition = (
            SqlChatConversation.user_id == user_id
            if project_id is None
            else SqlChatConversation.project_id == project_id
        )
        totals = self.session.execute(
            select(
                func.coalesce(func.sum(SqlChatTurn.reserved_tokens), 0),
                func.coalesce(func.sum(SqlChatTurn.reserved_cost_microusd), 0),
            )
            .join(SqlChatConversation)
            .where(condition, SqlChatTurn.created_at >= since)
        ).one()
        return int(totals[0]), int(totals[1])

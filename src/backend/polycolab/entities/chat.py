"""Materialized private chat history."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class ChatConversation:
    id: UUID
    user_id: UUID
    project_id: UUID | None
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ChatTurn:
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

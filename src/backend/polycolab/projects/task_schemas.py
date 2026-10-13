"""Durable project-task HTTP contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from polycolab.app.schemas import ApiModel, RequestModel


class ProjectTaskCreate(RequestModel):
    client_request_id: UUID
    title: str = Field(min_length=1, max_length=300)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task title must not be blank")
        return value.strip()


class ProjectTaskUpdate(RequestModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("task title must not be blank")
        return value.strip() if value is not None else None


class ProjectTaskRead(ApiModel):
    id: UUID
    project_id: UUID
    title: str
    branch: str
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

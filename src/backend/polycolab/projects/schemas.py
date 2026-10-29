"""HTTP schemas owned by the projects capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from polycolab.app.cursors import Collection
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import InvitationStatus, ProjectRole, ProjectVisibility


class ProjectCreate(RequestModel):
    workspace_mode: Literal["default", "linear", "git"] = "git"
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC


class ProjectUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility | None = None
    archived: bool | None = None


class ProjectMemberRead(ApiModel):
    workspace_mode: Literal["default", "linear", "git"] = "git"
    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # This is a display capability only. The policy layer remains authoritative
    # for every mutation, and public projections intentionally omit it.
    current_user_role: ProjectRole
    member_count: int = Field(ge=0)


class PublicProjectRead(ApiModel):
    """Safe anonymous shape; never add members, owner, invitations, or run data."""

    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProjectCollection(Collection[ProjectMemberRead | PublicProjectRead]):
    total: int = Field(ge=0)


class MembershipCreate(RequestModel):
    user_id: UUID | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    role: ProjectRole

    @model_validator(mode="after")
    def exact_target(self) -> MembershipCreate:
        if (self.user_id is None) == (self.username is None):
            raise ValueError("provide exactly one of user_id or username")
        return self


class MembershipUpdate(RequestModel):
    role: ProjectRole


class MembershipRead(ApiModel):
    user_id: UUID
    username: str | None
    display_name: str | None
    role: ProjectRole
    created_at: datetime


class InvitationCreate(RequestModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    role: ProjectRole


class InvitationRead(ApiModel):
    id: UUID
    email: str
    role: ProjectRole
    expires_at: datetime
    status: InvitationStatus
    created_at: datetime


class InvitationAccepted(ApiModel):
    project_id: UUID
    role: ProjectRole


class InvitationAccept(RequestModel):
    token: SecretStr


__all__ = [
    "ProjectCreate",
    "ProjectUpdate",
    "ProjectMemberRead",
    "PublicProjectRead",
    "MembershipCreate",
    "MembershipUpdate",
    "MembershipRead",
    "InvitationCreate",
    "InvitationRead",
    "InvitationAccepted",
    "InvitationAccept",
]

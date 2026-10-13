"""HTTP schemas owned by the projects capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from polycolab.app.cursors import Collection
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import InvitationStatus, ProjectRole, ProjectVisibility
from polycolab.research.contracts import ProjectCopyCreate


class ProjectVersionCopyCreate(RequestModel):
    workspace_mode: Literal["linear", "git"] = "git"
    source_object_version_id: UUID
    project_id: UUID | None = None
    project_name: str = Field(default="Research project", min_length=1, max_length=200)
    project_visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"

    def historical_command(self) -> ProjectCopyCreate:
        return ProjectCopyCreate(
            revision_id=self.source_object_version_id,
            **self.model_dump(exclude={"source_object_version_id"}, exclude_unset=True),
        )


class ProjectVersionCopyRead(ApiModel):
    project_id: UUID
    object_id: UUID
    object_version_id: UUID
    source_object_version_id: UUID


class ProjectCreate(RequestModel):
    workspace_mode: Literal["linear", "git"] = "git"
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC


class ProjectUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: ProjectVisibility | None = None
    archived: bool | None = None


class ProjectMemberRead(ApiModel):
    workspace_mode: Literal["linear", "git"] = "git"
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

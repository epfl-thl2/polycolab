"""HTTP schemas owned by the workspaces capability."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, SecretStr, model_validator

from polycolab.app.cursors import Collection
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.enums import InvitationStatus, WorkspaceRole, WorkspaceVisibility
from polycolab.research.contracts import WorkspaceCopyCreate


class WorkspaceVersionCopyCreate(RequestModel):
    source_object_version_id: UUID
    project_id: UUID | None = None
    workspace_name: str = Field(default="Research workspace", min_length=1, max_length=200)
    workspace_visibility: Literal["PUBLIC", "PRIVATE"] = "PUBLIC"

    def historical_command(self) -> WorkspaceCopyCreate:
        return WorkspaceCopyCreate(
            revision_id=self.source_object_version_id,
            project_id=self.project_id,
            workspace_name=self.workspace_name,
            workspace_visibility=self.workspace_visibility,
        )


class WorkspaceVersionCopyRead(ApiModel):
    project_id: UUID
    object_id: UUID
    object_version_id: UUID
    source_object_version_id: UUID


class WorkspaceCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: WorkspaceVisibility = WorkspaceVisibility.PUBLIC


class WorkspaceUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=20_000)
    visibility: WorkspaceVisibility | None = None
    archived: bool | None = None


class WorkspaceMemberRead(ApiModel):
    id: UUID
    name: str
    description: str | None
    visibility: WorkspaceVisibility
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # This is a display capability only. The policy layer remains authoritative
    # for every mutation, and public projections intentionally omit it.
    current_user_role: WorkspaceRole
    member_count: int = Field(ge=0)


class PublicWorkspaceRead(ApiModel):
    """Safe anonymous shape; never add members, owner, invitations, or run data."""

    id: UUID
    name: str
    description: str | None
    visibility: WorkspaceVisibility
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WorkspaceCollection(Collection[WorkspaceMemberRead | PublicWorkspaceRead]):
    total: int = Field(ge=0)


class MembershipCreate(RequestModel):
    user_id: UUID | None = None
    username: str | None = Field(default=None, min_length=3, max_length=80)
    role: WorkspaceRole

    @model_validator(mode="after")
    def exact_target(self) -> MembershipCreate:
        if (self.user_id is None) == (self.username is None):
            raise ValueError("provide exactly one of user_id or username")
        return self


class MembershipUpdate(RequestModel):
    role: WorkspaceRole


class MembershipRead(ApiModel):
    user_id: UUID
    username: str | None
    display_name: str | None
    role: WorkspaceRole
    created_at: datetime


class InvitationCreate(RequestModel):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")
    role: WorkspaceRole


class InvitationRead(ApiModel):
    id: UUID
    email: str
    role: WorkspaceRole
    expires_at: datetime
    status: InvitationStatus
    created_at: datetime


class InvitationAccepted(ApiModel):
    project_id: UUID
    role: WorkspaceRole


class InvitationAccept(RequestModel):
    token: SecretStr


__all__ = [
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceMemberRead",
    "PublicWorkspaceRead",
    "MembershipCreate",
    "MembershipUpdate",
    "MembershipRead",
    "InvitationCreate",
    "InvitationRead",
    "InvitationAccepted",
    "InvitationAccept",
]

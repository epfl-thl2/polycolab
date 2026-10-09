"""Workspace persistence interface consumed by application operations."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from polycolab.entities.enums import WorkspaceRole, WorkspaceVisibility
from polycolab.entities.workspaces import (
    Invitation,
    Membership,
    Workspace,
    WorkspaceAccess,
)


class WorkspaceStore(Protocol):
    def member_counts(self, project_ids: list[UUID]) -> dict[UUID, int]: ...

    def count_visible(
        self,
        *,
        user_id: UUID | None,
        members_only: bool,
        query: str | None,
        category: str | None = None,
    ) -> int: ...

    def list_visible(
        self,
        *,
        user_id: UUID | None,
        members_only: bool,
        query: str | None,
        after: UUID | None,
        limit: int,
        category: str | None = None,
        sort: str = "updated",
    ) -> tuple[WorkspaceAccess, ...]: ...

    def workspace(self, project_id: UUID, *, lock: bool = False) -> Workspace | None: ...

    def membership(
        self, project_id: UUID, user_id: UUID, *, lock: bool = False
    ) -> Membership | None: ...

    def update_settings(
        self,
        project_id: UUID,
        *,
        name: str,
        description: str | None,
        visibility: WorkspaceVisibility,
        archived_at: datetime | None,
    ) -> Workspace: ...

    def mark_deleted(self, project_id: UUID, *, at: datetime) -> None: ...

    def owners(self, project_id: UUID) -> tuple[Membership, ...]: ...

    def create_workspace(
        self,
        *,
        creator_id: UUID,
        name: str,
        description: str | None,
        visibility: WorkspaceVisibility,
    ) -> Workspace: ...

    def add_membership(
        self, *, project_id: UUID, user_id: UUID, role: WorkspaceRole, invited_by: UUID | None
    ) -> Membership: ...

    def change_role(self, membership_id: UUID, role: WorkspaceRole) -> Membership: ...

    def remove_membership(self, membership_id: UUID) -> None: ...

    def close_external_runs(self, project_id: UUID, user_id: UUID) -> None: ...

    def create_invitation(
        self,
        *,
        project_id: UUID,
        email: str,
        role: WorkspaceRole,
        token_digest: str,
        invited_by: UUID,
        expires_at: datetime,
    ) -> Invitation: ...

    def invitation_by_digest(self, digest: str) -> Invitation | None: ...

    def revoke_invitation(self, invitation_id: UUID, *, at: datetime) -> None: ...

    def accept_invitation(self, invitation_id: UUID, *, user_id: UUID, at: datetime) -> None: ...

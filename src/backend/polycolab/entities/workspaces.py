"""Workspace application state and projections, independent of SQL tables."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from polycolab.entities.enums import InvitationStatus, WorkspaceRole, WorkspaceVisibility


@dataclass(frozen=True, slots=True)
class Workspace:
    """The workspace resource, independent of a particular caller."""

    id: UUID
    name: str
    description: str | None
    visibility: WorkspaceVisibility
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class Membership:
    id: UUID
    project_id: UUID
    user_id: UUID
    role: WorkspaceRole
    invited_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceMemberAccess:
    """A workspace authorized for a caller with required membership."""

    workspace: Workspace
    membership: Membership


@dataclass(frozen=True, slots=True)
class Invitation:
    """Invitation state; the persisted token digest is deliberately omitted."""

    id: UUID
    project_id: UUID
    email: str
    role: WorkspaceRole
    invited_by_user_id: UUID
    expires_at: datetime
    status: InvitationStatus
    accepted_by_user_id: UUID | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    """A visible workspace and this caller's optional membership."""

    workspace: Workspace
    membership: Membership | None

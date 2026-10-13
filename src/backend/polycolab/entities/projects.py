"""Project application state and projections, independent of SQL tables."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from polycolab.entities.enums import InvitationStatus, ProjectRole, ProjectVisibility


@dataclass(frozen=True, slots=True)
class Project:
    """The project resource, independent of a particular caller."""

    id: UUID
    name: str
    description: str | None
    visibility: ProjectVisibility
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    deleted_at: datetime | None
    workspace_mode: str = "git"


@dataclass(frozen=True, slots=True)
class Membership:
    id: UUID
    project_id: UUID
    user_id: UUID
    role: ProjectRole
    invited_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectMemberAccess:
    """A project authorized for a caller with required membership."""

    project: Project
    membership: Membership


@dataclass(frozen=True, slots=True)
class Invitation:
    """Invitation state; the persisted token digest is deliberately omitted."""

    id: UUID
    project_id: UUID
    email: str
    role: ProjectRole
    invited_by_user_id: UUID
    expires_at: datetime
    status: InvitationStatus
    accepted_by_user_id: UUID | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """A visible project and this caller's optional membership."""

    project: Project
    membership: Membership | None

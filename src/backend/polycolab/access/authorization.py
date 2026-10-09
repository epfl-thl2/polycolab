"""Reusable workspace policy primitives for routes, context construction, and tools."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from polycolab.access.actors import Actor, ActorKind, ActorOperation
from polycolab.entities.enums import WorkspaceRole, WorkspaceVisibility
from polycolab.entities.workspaces import Membership, Workspace, WorkspaceMemberAccess
from polycolab.transaction import Transaction


class PublicWorkspaceState(Protocol):
    @property
    def visibility(self) -> WorkspaceVisibility: ...

    @property
    def archived_at(self) -> datetime | None: ...

    @property
    def deleted_at(self) -> datetime | None: ...


class WorkspaceAction(StrEnum):
    VIEW = "VIEW"
    MANAGE_SETTINGS = "MANAGE_SETTINGS"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    ARCHIVE = "ARCHIVE"
    DELETE = "DELETE"
    CREATE_RESEARCH = "CREATE_RESEARCH"
    COMMENT = "COMMENT"
    REVIEW_PROPOSALS = "REVIEW_PROPOSALS"
    RUN_AGENTS = "RUN_AGENTS"


class AuthorizationDenied(Exception):
    pass


class WorkspaceNotFound(Exception):
    pass


ROLE_ACTIONS: dict[WorkspaceRole, frozenset[WorkspaceAction]] = {
    WorkspaceRole.OWNER: frozenset(WorkspaceAction),
    WorkspaceRole.CONTRIBUTOR: frozenset(
        {
            WorkspaceAction.VIEW,
            WorkspaceAction.CREATE_RESEARCH,
            WorkspaceAction.COMMENT,
            WorkspaceAction.REVIEW_PROPOSALS,
            WorkspaceAction.RUN_AGENTS,
        }
    ),
    WorkspaceRole.READ_ONLY: frozenset({WorkspaceAction.VIEW}),
}

# All mutations that recheck workspace authority acquire these rows in this order.
# Future scope/entity locks and moderation locks must follow the same prefix.
AUTHORIZATION_LOCK_ORDER = ("project", "membership")


def require_human_actor(actor: Actor, *, action: str) -> None:
    """Guard an operation whose authority cannot be delegated to an agent."""

    if actor.kind is not ActorKind.HUMAN:
        raise AuthorizationDenied(f"{action} requires a human actor")


def _require_scoped_operation(
    actor: Actor,
    operation: ActorOperation,
    *,
    project_id: UUID | None = None,
    ownership_scope_id: UUID | None = None,
) -> None:
    if actor.kind is ActorKind.HUMAN:
        return
    if actor.kind is not ActorKind.AGENT or operation not in actor.operation_scope:
        raise AuthorizationDenied(f"missing delegated operation: {operation.value}")
    if project_id is not None and actor.project_id != project_id:
        raise AuthorizationDenied("agent project scope mismatch")
    if ownership_scope_id is not None and actor.ownership_scope_id != ownership_scope_id:
        raise AuthorizationDenied("agent ownership scope mismatch")


def require_catalogue_admission(actor: Actor) -> None:
    require_human_actor(actor, action="catalogue admission")


def require_catalogue_promotion(actor: Actor) -> None:
    require_human_actor(actor, action="catalogue promotion")


def require_catalogue_edit(actor: Actor) -> None:
    require_human_actor(actor, action="catalogue edit")


def require_contribution_creation(
    actor: Actor, *, project_id: UUID | None = None, ownership_scope_id: UUID | None = None
) -> None:
    _require_scoped_operation(
        actor,
        ActorOperation.CONTRIBUTION_CREATE,
        project_id=project_id,
        ownership_scope_id=ownership_scope_id,
    )


def require_contribution_edit(
    actor: Actor, *, project_id: UUID | None = None, ownership_scope_id: UUID | None = None
) -> None:
    _require_scoped_operation(
        actor,
        ActorOperation.CONTRIBUTION_EDIT,
        project_id=project_id,
        ownership_scope_id=ownership_scope_id,
    )


def require_public_participation(
    actor: Actor, *, project_id: UUID | None = None, ownership_scope_id: UUID | None = None
) -> None:
    _require_scoped_operation(
        actor,
        ActorOperation.PUBLIC_PARTICIPATION,
        project_id=project_id,
        ownership_scope_id=ownership_scope_id,
    )


def require_workspace_write(actor: Actor, *, project_id: UUID | None = None) -> None:
    _require_scoped_operation(actor, ActorOperation.WORKSPACE_WRITE, project_id=project_id)


def require_publication(actor: Actor) -> None:
    require_human_actor(actor, action="publication")


def require_workspace_management(actor: Actor) -> None:
    require_human_actor(actor, action="project management")


def require_manage_members(actor: Actor) -> None:
    require_human_actor(actor, action="membership management")


def require_manage_credentials(actor: Actor) -> None:
    require_human_actor(actor, action="credential management")


def require_moderation(actor: Actor) -> None:
    require_human_actor(actor, action="moderation")


def require_proposal_submission(actor: Actor) -> None:
    _require_scoped_operation(actor, ActorOperation.PROPOSAL_SUBMISSION)


def require_proposal_review(actor: Actor) -> None:
    require_human_actor(actor, action="proposal review")


def lock_workspace_authorization(
    transaction: Transaction, *, project_id: UUID, user_id: UUID
) -> tuple[Workspace | None, Membership | None]:
    """Lock workspace then membership before checking mutable authority.

    Archive, deletion, membership revocation, and moderation mutations must
    acquire these rows in this order so authorization and the protected write
    share one transaction boundary.
    """

    workspace = transaction.workspaces.workspace(project_id, lock=True)
    membership = transaction.workspaces.membership(project_id, user_id, lock=True)
    return workspace, membership


class WorkspacePolicy:
    """Loads current membership on each call; no permission is cached in a token."""

    def membership(
        self, transaction: Transaction, project_id: UUID, user_id: UUID
    ) -> Membership | None:
        return transaction.workspaces.membership(project_id, user_id)

    def can(
        self, transaction: Transaction, project_id: UUID, user_id: UUID, action: WorkspaceAction
    ) -> bool:
        workspace = transaction.workspaces.workspace(project_id)
        if workspace is None or workspace.deleted_at is not None:
            return False
        if workspace.archived_at is not None and action not in {
            WorkspaceAction.VIEW,
            WorkspaceAction.MANAGE_SETTINGS,
            WorkspaceAction.ARCHIVE,
            WorkspaceAction.DELETE,
        }:
            return False
        membership = self.membership(transaction, project_id, user_id)
        return membership is not None and action in ROLE_ACTIONS[membership.role]

    def require_scope(
        self, transaction: Transaction, project_id: UUID, user_id: UUID, action: WorkspaceAction
    ) -> WorkspaceMemberAccess:
        if action is WorkspaceAction.VIEW:
            workspace = transaction.workspaces.workspace(project_id)
            membership = self.membership(transaction, project_id, user_id)
        else:
            workspace, membership = lock_workspace_authorization(
                transaction, project_id=project_id, user_id=user_id
            )
        if workspace is None or workspace.deleted_at is not None:
            raise WorkspaceNotFound
        # A non-member is deliberately indistinguishable from an unknown workspace.
        if membership is None:
            raise WorkspaceNotFound
        # Archived workspaces are read-only until an owner changes settings to
        # unarchive them; membership, research, agent, and review mutations stop.
        if workspace.archived_at is not None and action not in {
            WorkspaceAction.VIEW,
            WorkspaceAction.MANAGE_SETTINGS,
            WorkspaceAction.ARCHIVE,
            WorkspaceAction.DELETE,
        }:
            raise AuthorizationDenied
        if action not in ROLE_ACTIONS[membership.role]:
            raise AuthorizationDenied
        return WorkspaceMemberAccess(workspace, membership)

    def can_read_public(self, workspace: PublicWorkspaceState | None) -> bool:
        return bool(
            workspace is not None
            and workspace.visibility is WorkspaceVisibility.PUBLIC
            and workspace.archived_at is None
            and workspace.deleted_at is None
        )


workspace_policy = WorkspacePolicy()

"""Application workspace operations with explicit shared transaction ownership."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from polycolab.accounts.delivery import InvitationDelivery
from polycolab.accounts.names import normalize_username, normalized_email
from polycolab.entities.accounts import IdentifiedUser, User
from polycolab.entities.enums import InvitationStatus, WorkspaceRole, WorkspaceVisibility
from polycolab.entities.time import utc_now
from polycolab.entities.workspaces import (
    Invitation,
    Membership,
    Workspace,
    WorkspaceAccess,
)
from polycolab.transaction import PersistenceConflict, Transaction


class DomainConflict(Exception):
    pass


class InvitationInvalid(Exception):
    pass


class MembershipTargetInvalid(Exception):
    pass


def count_visible(
    transaction: Transaction,
    *,
    user_id: UUID | None,
    members_only: bool,
    query: str | None,
    category: str | None = None,
) -> int:
    if members_only and user_id is None:
        raise ValueError("member workspace listing requires an authenticated user")
    return transaction.workspaces.count_visible(
        user_id=user_id, members_only=members_only, query=query, category=category
    )


def list_visible(
    transaction: Transaction,
    *,
    user_id: UUID | None,
    members_only: bool,
    query: str | None,
    after: UUID | None,
    limit: int,
    category: str | None = None,
    sort: str = "updated",
) -> tuple[WorkspaceAccess, ...]:
    if members_only and user_id is None:
        raise ValueError("member workspace listing requires an authenticated user")
    return transaction.workspaces.list_visible(
        user_id=user_id,
        members_only=members_only,
        query=query,
        after=after,
        limit=limit,
        category=category,
        sort=sort,
    )


def create_workspace(
    transaction: Transaction,
    *,
    creator: IdentifiedUser,
    name: str,
    description: str | None,
    visibility: WorkspaceVisibility,
    commit: bool = True,
) -> Workspace:
    """Create workspace, scope and owner atomically in the caller's transaction."""
    workspace = transaction.workspaces.create_workspace(
        creator_id=creator.id, name=name, description=description, visibility=visibility
    )
    if commit:
        transaction.commit()
    return workspace


def add_membership(
    transaction: Transaction,
    *,
    project_id: UUID,
    user_id: UUID,
    role: WorkspaceRole,
    invited_by: UUID,
) -> Membership:
    if transaction.accounts.user(user_id) is None:
        raise InvitationInvalid
    try:
        membership = transaction.workspaces.add_membership(
            project_id=project_id, user_id=user_id, role=role, invited_by=invited_by
        )
        transaction.commit()
    except PersistenceConflict as error:
        transaction.rollback()
        raise DomainConflict from error
    return membership


def resolve_membership_username(transaction: Transaction, *, username: str) -> User:
    """Resolve one exact built-in username without exposing account discovery."""
    try:
        normalized = normalize_username(username)
    except ValueError as error:
        raise MembershipTargetInvalid from error
    account = transaction.accounts.member_account(normalized)
    if account is None:
        raise MembershipTargetInvalid
    user = transaction.accounts.user_by_subject("polycolab-local", str(account.id))
    if user is None:
        user = transaction.accounts.create_user(
            issuer="polycolab-local",
            subject=str(account.id),
            email=None,
            display_name=account.display_name or account.username,
        )
    return user


def change_membership_role(
    transaction: Transaction, *, project_id: UUID, user_id: UUID, role: WorkspaceRole
) -> Membership:
    # Serialize owner-set changes before locking the selected membership.
    transaction.workspaces.workspace(project_id, lock=True)
    target = transaction.workspaces.membership(project_id, user_id, lock=True)
    if target is None:
        raise InvitationInvalid
    owners = transaction.workspaces.owners(project_id)
    if target.role is WorkspaceRole.OWNER and role is not WorkspaceRole.OWNER and len(owners) == 1:
        raise DomainConflict
    if role is WorkspaceRole.READ_ONLY:
        transaction.workspaces.close_external_runs(project_id, user_id)
    changed = transaction.workspaces.change_role(target.id, role)
    transaction.commit()
    return changed


def remove_membership(transaction: Transaction, *, project_id: UUID, user_id: UUID) -> None:
    transaction.workspaces.workspace(project_id, lock=True)
    target = transaction.workspaces.membership(project_id, user_id, lock=True)
    if target is None:
        raise InvitationInvalid
    owners = transaction.workspaces.owners(project_id)
    if target.role is WorkspaceRole.OWNER and len(owners) == 1:
        raise DomainConflict
    transaction.workspaces.close_external_runs(project_id, user_id)
    transaction.workspaces.remove_membership(target.id)
    transaction.commit()


def create_invitation(
    transaction: Transaction,
    *,
    project_id: UUID,
    email: str,
    role: WorkspaceRole,
    invited_by: UUID,
    delivery: InvitationDelivery,
) -> Invitation:
    """Persist only after the opaque secret reaches a configured delivery adapter."""
    token = secrets.token_urlsafe(32)
    invitation = None
    try:
        invitation = transaction.workspaces.create_invitation(
            project_id=project_id,
            email=normalized_email(email),
            role=role,
            token_digest=hashlib.sha256(token.encode()).hexdigest(),
            invited_by=invited_by,
            expires_at=utc_now() + timedelta(days=7),
        )
        delivery.deliver(invitation.id, invitation.email, token)
        transaction.commit()
    except Exception:
        try:
            if invitation is not None:
                delivery.retract(invitation.id)
        except Exception:
            pass  # Best-effort cleanup must not hide the original failure.
        finally:
            transaction.rollback()
        raise
    return invitation


def revoke_invitation(transaction: Transaction, invitation: Invitation) -> None:
    if invitation.status is InvitationStatus.PENDING:
        transaction.workspaces.revoke_invitation(invitation.id, at=utc_now())
        transaction.commit()


def accept_invitation(
    transaction: Transaction, *, token: str, user: IdentifiedUser
) -> tuple[UUID, WorkspaceRole]:
    digest = hashlib.sha256(token.encode()).hexdigest()
    invitation = transaction.workspaces.invitation_by_digest(digest)
    if invitation is None or invitation.status is not InvitationStatus.PENDING:
        raise InvitationInvalid
    workspace = transaction.workspaces.workspace(invitation.project_id, lock=True)
    if workspace is None or workspace.deleted_at is not None or workspace.archived_at is not None:
        raise InvitationInvalid
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise InvitationInvalid
    if user.email is None or user.email.casefold() != invitation.email.casefold():
        raise InvitationInvalid
    existing = transaction.workspaces.membership(invitation.project_id, user.id)
    if existing is None:
        transaction.workspaces.add_membership(
            project_id=invitation.project_id,
            user_id=user.id,
            role=invitation.role,
            invited_by=invitation.invited_by_user_id,
        )
    transaction.workspaces.accept_invitation(invitation.id, user_id=user.id, at=utc_now())
    transaction.commit()
    return invitation.project_id, invitation.role


def member_counts(transaction: Transaction, project_ids: list[UUID]) -> dict[UUID, int]:
    """Count current memberships for a page of workspaces."""
    return transaction.workspaces.member_counts(project_ids)

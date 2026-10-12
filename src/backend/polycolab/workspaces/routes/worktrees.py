"""Member-visible native worktrees; conversations remain creator-private."""

import base64
from uuid import UUID

from fastapi import APIRouter, Request, Response

from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.entities.repositories import RepositoryError
from polycolab.workspaces.repository_schemas import RepositoryFile
from polycolab.workspaces.repository_service import decode_changes
from polycolab.workspaces.routes.repository import RetryKey, service
from polycolab.workspaces.worktree_schemas import (
    WorktreeCommit,
    WorktreeCreate,
    WorktreeRead,
    WorktreeRemove,
    WorktreeRevision,
    WorktreeSave,
    WorktreeSaved,
)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/worktrees", tags=["worktrees"])


@router.get("", response_model=list[WorktreeRead], operation_id="listWorktrees")
def list_worktrees(
    workspace_id: UUID,
    request: Request,
    response: Response,
    db: DbSession,
    user: CurrentUser,
    include_removed: bool = False,
) -> list[WorktreeRead]:
    response.headers["Cache-Control"] = "no-store"
    instance = service(request, db, workspace_id, user.id).native_service()
    with instance.open():
        instance.ensure_native()
        return [
            WorktreeRead.model_validate(instance.state(task))
            for task in instance.store.tasks(workspace_id, include_removed)
        ]


@router.post("", response_model=WorktreeRead, status_code=201, operation_id="createWorktree")
def create(
    workspace_id: UUID, body: WorktreeCreate, request: Request, db: DbSession, user: CurrentUser
) -> WorktreeRead:
    instance = service(request, db, workspace_id, user.id).native_service()
    task = instance.create_worktree(
        body.client_request_id, body.title, body.branch, body.start_branch
    )
    with instance.open():
        return WorktreeRead.model_validate(instance.state(task))


@router.get("/{worktree_id}", response_model=WorktreeRead, operation_id="getWorktree")
def get(
    workspace_id: UUID,
    worktree_id: UUID,
    request: Request,
    response: Response,
    db: DbSession,
    user: CurrentUser,
) -> WorktreeRead:
    response.headers["Cache-Control"] = "no-store"
    instance = service(request, db, workspace_id, user.id).native_service()
    with instance.open():
        instance.ensure_native()
        return WorktreeRead.model_validate(
            instance.state(instance.store.task(workspace_id, worktree_id))
        )


@router.get("/{worktree_id}/file", response_model=RepositoryFile, operation_id="getWorktreeFile")
def file(
    workspace_id: UUID,
    worktree_id: UUID,
    path: str,
    revision: str,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> RepositoryFile:
    instance = service(request, db, workspace_id, user.id).native_service()
    with instance.open():
        task = instance.store.task(workspace_id, worktree_id)
        instance.require_available(task)
        if not instance.files.contains(worktree_id, revision):
            raise RepositoryError("worktree_revision_not_found", 404)
        return RepositoryFile(
            commit=revision,
            path=path,
            content_base64=base64.b64encode(instance.git.read(revision, path)).decode(),
        )


@router.get("/{worktree_id}/diff", operation_id="diffWorktree")
def diff(
    workspace_id: UUID,
    worktree_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    revision: str | None = None,
) -> str:
    instance = service(request, db, workspace_id, user.id).native_service()
    with instance.open():
        task = instance.store.task(workspace_id, worktree_id)
        current = instance.require_available(task)
        if revision and revision != current:
            raise RepositoryError("worktree_stale_revision")
        return instance.git.diff(instance.git.head(task.branch), current)


@router.post("/{worktree_id}/save", response_model=WorktreeSaved, operation_id="saveWorktree")
def save(
    workspace_id: UUID,
    worktree_id: UUID,
    body: WorktreeSave,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorktreeSaved:
    revision = (
        service(request, db, workspace_id, user.id)
        .native_service()
        .change(
            worktree_id,
            body.expected_revision,
            key,
            "save",
            body.model_dump(),
            decode_changes([(c.path, c.content_base64) for c in body.changes]),
        )
    )
    return WorktreeSaved(revision=revision)


@router.post("/{worktree_id}/commit", response_model=WorktreeSaved, operation_id="commitWorktree")
def commit(
    workspace_id: UUID,
    worktree_id: UUID,
    body: WorktreeCommit,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorktreeSaved:
    revision = (
        service(request, db, workspace_id, user.id)
        .native_service()
        .change(
            worktree_id,
            body.expected_revision,
            key,
            "commit",
            body.model_dump(),
            message=body.message,
        )
    )
    return WorktreeSaved(revision=revision)


@router.post("/{worktree_id}/discard", response_model=WorktreeSaved, operation_id="discardWorktree")
def discard(
    workspace_id: UUID,
    worktree_id: UUID,
    body: WorktreeRevision,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorktreeSaved:
    revision = (
        service(request, db, workspace_id, user.id)
        .native_service()
        .change(worktree_id, body.expected_revision, key, "discard", {"discard": body.model_dump()})
    )
    return WorktreeSaved(revision=revision)


@router.post("/{worktree_id}/remove", response_model=WorktreeRead, operation_id="removeWorktree")
def remove(
    workspace_id: UUID,
    worktree_id: UUID,
    body: WorktreeRemove,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> WorktreeRead:
    instance = service(request, db, workspace_id, user.id).native_service()
    if instance.store.task(workspace_id, worktree_id).branch == "main":
        raise RepositoryError("worktree_main_cannot_remove")
    # Discard has its own receipt; repeated removes are safe and preserve metadata.
    if body.discard_changes:
        instance.change(
            worktree_id, body.expected_revision, key, "discard", {"remove": body.model_dump()}
        )
    task = instance.lifecycle(
        worktree_id,
        removed=True,
        expected=body.expected_revision if not body.discard_changes else None,
    )
    with instance.open():
        return WorktreeRead.model_validate(instance.state(task))


@router.post("/{worktree_id}/restore", response_model=WorktreeRead, operation_id="restoreWorktree")
def restore(
    workspace_id: UUID, worktree_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> WorktreeRead:
    instance = service(request, db, workspace_id, user.id).native_service()
    task = instance.lifecycle(worktree_id, removed=False)
    with instance.open():
        return WorktreeRead.model_validate(instance.state(task))

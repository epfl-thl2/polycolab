"""Member-only working files. File history never grants public research access."""

import base64
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.stores.repositories import SqlRepositoryStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.projects.git_storage import GitRepository, branch_name
from polycolab.projects.repository_schemas import (
    RepositoryCommit,
    RepositoryEntry,
    RepositoryFile,
    RepositoryMerge,
    RepositoryMergePreview,
    RepositoryRunState,
    RepositorySave,
    RepositorySaved,
    RepositorySessionState,
    RepositoryState,
)
from polycolab.projects.repository_service import RepositoryService, decode_changes

router = APIRouter(prefix="/api/v1/projects/{project_id}/repository", tags=["project files"])
RetryKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)]


def service(request: Request, db: DbSession, project_id: UUID, user_id: UUID) -> RepositoryService:
    settings = request.app.state.settings
    transaction = SqlAlchemyTransaction(db)
    project_policy.require_scope(transaction, project_id, user_id, ProjectAction.VIEW)
    if settings.project_repository_directory is None:
        raise RepositoryError("repository_disabled", 503)
    return RepositoryService(
        transaction,
        SqlRepositoryStore(db),
        GitRepository(
            settings.project_repository_directory,
            project_id,
            settings.project_repository_max_bytes,
        ),
        project_id,
        user_id,
    )


@router.get("", response_model=RepositoryState, operation_id="getProjectRepository")
def state(
    project_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    response: Response,
    branch: str = "main",
) -> RepositoryState:
    response.headers["Cache-Control"] = "no-store"
    tx = SqlAlchemyTransaction(db)
    project_policy.require_scope(tx, project_id, user.id, ProjectAction.VIEW)
    if request.app.state.settings.project_repository_directory is None:
        return RepositoryState(enabled=False, branch=branch)
    instance = service(request, db, project_id, user.id)
    with instance.open() as git:
        commit = git.head(branch_name(branch))
        writable = (
            project_policy.can(tx, project_id, user.id, ProjectAction.CREATE_RESEARCH)
            and project_policy.require_scope(
                tx, project_id, user.id, ProjectAction.VIEW
            ).project.workspace_mode
            == "git"
            and not tx.linear.conversion_pending(project_id)
        )
        if instance.store.branch_active(project_id, branch) or instance.store.branch_archived(
            project_id, branch
        ):
            writable = False
        return RepositoryState(
            enabled=True,
            branch=branch,
            commit=commit,
            branches=git.branches(),
            files=[
                RepositoryEntry(path=path, size=item[2], executable=item[0] == "100755")
                for path, item in git.entries(commit).items()
            ],
            writable=writable,
        )


@router.get("/file", response_model=RepositoryFile, operation_id="getProjectFile")
def file(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser, path: str, commit: str
) -> RepositoryFile:
    with service(request, db, project_id, user.id).open() as git:
        return RepositoryFile(
            commit=git.accessible(commit),
            path=path,
            content_base64=base64.b64encode(git.read(commit, path)).decode(),
        )


@router.get(
    "/history", response_model=list[RepositoryCommit], operation_id="listProjectFileHistory"
)
def history(
    project_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    branch: str = "main",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[RepositoryCommit]:
    with service(request, db, project_id, user.id).open() as git:
        return [
            RepositoryCommit.model_validate(item) for item in git.history(git.head(branch), limit)
        ]


@router.get("/diff", operation_id="diffProjectFiles")
def diff(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser, base: str, target: str
) -> str:
    with service(request, db, project_id, user.id).open() as git:
        return git.diff(git.accessible(base), git.accessible(target))


@router.post("/changes", response_model=RepositorySaved, operation_id="saveProjectFiles")
def save(
    project_id: UUID,
    body: RepositorySave,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> RepositorySaved:
    instance = service(request, db, project_id, user.id)
    commit = instance.save(
        branch=body.branch,
        expected=body.expected_commit,
        key=key,
        changes=decode_changes([(c.path, c.content_base64) for c in body.changes]),
        payload=body.model_dump(),
    )
    return RepositorySaved(commit=commit)


@router.get("/merge", response_model=RepositoryMergePreview, operation_id="previewProjectMerge")
def preview(
    project_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    source: str,
    target: str = "main",
) -> RepositoryMergePreview:
    return RepositoryMergePreview.model_validate(
        service(request, db, project_id, user.id).preview(target, source)
    )


@router.post("/merge", response_model=RepositorySaved, operation_id="mergeProjectFiles")
def merge(
    project_id: UUID,
    body: RepositoryMerge,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> RepositorySaved:
    commit = service(request, db, project_id, user.id).merge(
        target=body.target,
        source=body.source,
        expected_target=body.expected_target,
        expected_source=body.expected_source,
        expected_target_revision=body.expected_target_revision,
        expected_source_revision=body.expected_source_revision,
        key=key,
        payload=body.model_dump(),
        resolutions=decode_changes([(c.path, c.content_base64) for c in body.resolutions])
        if body.resolutions is not None
        else None,
    )
    return RepositorySaved(commit=commit)


@router.get(
    "/sessions/{session_id}",
    response_model=RepositorySessionState,
    operation_id="getSessionRepository",
)
def session_state(
    project_id: UUID, session_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> RepositorySessionState:
    instance = service(request, db, project_id, user.id)
    instance.authorize()
    binding = instance.store.session(project_id, session_id)
    return RepositorySessionState(
        enabled=binding.enabled, branch=binding.branch if binding.enabled else None
    )


@router.put(
    "/sessions/{session_id}",
    response_model=RepositorySessionState,
    operation_id="enableSessionRepository",
)
def enable_session(
    project_id: UUID, session_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> RepositorySessionState:
    if request.app.state.settings.runtime_codex_image is None:
        raise RepositoryError("repository_hosted_unavailable", 409)
    branch = service(request, db, project_id, user.id).enable_session(session_id)
    return RepositorySessionState(enabled=True, branch=branch)


@router.get(
    "/runs/{run_id}",
    response_model=RepositoryRunState,
    response_model_exclude_unset=True,
    operation_id="getRunRepository",
)
def run_state(
    project_id: UUID, run_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> RepositoryRunState:
    instance = service(request, db, project_id, user.id)
    binding = instance.store.run(run_id)
    if binding is None:
        return RepositoryRunState(input_commit=None, output_commit=None)
    instance.store.session(project_id, binding.session_id)
    if binding.input_revision:
        return RepositoryRunState(
            input_commit=binding.input_commit,
            output_commit=binding.input_commit if binding.output_commit else None,
            input_revision=binding.input_revision,
            output_revision=binding.output_commit,
            worktree_id=binding.worktree_id,
        )
    return RepositoryRunState(
        input_commit=binding.input_commit, output_commit=binding.output_commit
    )

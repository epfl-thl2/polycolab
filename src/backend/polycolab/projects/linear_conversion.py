"""Resumable Git-to-linear cutover, preserving original checkouts and refs."""

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.db.models import SqlAgentRun, SqlProject
from polycolab.db.models.linear import SqlLinearConversion
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.linear_factory import repository_service
from polycolab.projects.linear_service import encode


def preview(
    settings: Settings, db: Session, project_id: UUID, user_id: UUID, worktree_id: UUID
) -> dict[str, object]:
    project_policy.require_scope(
        SqlAlchemyTransaction(db), project_id, user_id, ProjectAction.MANAGE_SETTINGS
    )
    instance = repository_service(settings, db, project_id, user_id).native_service()
    with instance.open():
        task = instance.store.task(project_id, worktree_id)
        revision = instance.require_available(task)
        return {
            "worktree_id": str(worktree_id),
            "revision": revision,
            "files": [name for name in instance.git.entries(revision)],
            "saved_changes": not instance.files.clean(task.id, task.branch),
        }


def convert(
    settings: Settings,
    db: Session,
    project_id: UUID,
    user_id: UUID,
    worktree_id: UUID,
    revision: str,
    key: str,
) -> None:
    from polycolab.projects.linear_factory import service

    instance = service(settings, db, project_id, user_id)
    native = repository_service(settings, db, project_id, user_id).native_service()
    with native.open():
        access = project_policy.require_scope(
            instance.tx, project_id, user_id, ProjectAction.MANAGE_SETTINGS
        )
        existing = db.get(SqlLinearConversion, project_id)
        if existing:
            if (
                existing.user_id,
                existing.source_worktree_id,
                existing.source_revision,
                existing.request_key,
            ) != (user_id, worktree_id, revision, key):
                raise RepositoryError("linear_conversion_in_progress")
            if existing.completed:
                return
        else:
            if access.project.workspace_mode != "git" or access.project.archived_at:
                raise RepositoryError("linear_conversion_unavailable")
            active = db.scalar(
                select(SqlAgentRun.id)
                .where(
                    SqlAgentRun.project_id == project_id,
                    SqlAgentRun.status.not_in(["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]),
                )
                .limit(1)
            )
            if active:
                raise RepositoryError("linear_conversion_runs_must_drain")
            task = native.store.task(project_id, worktree_id)
            if native.require_available(task) != revision:
                raise RepositoryError("worktree_stale_revision")
            db.add(
                SqlLinearConversion(
                    project_id=project_id,
                    user_id=user_id,
                    source_worktree_id=worktree_id,
                    source_revision=revision,
                    request_key=key,
                )
            )
            db.commit()
        files = [
            (name, mode, native.git.read(revision, name))
            for name, (mode, _, _) in native.git.entries(revision).items()
        ]
    commands = []
    for name, mode, content in files:
        try:
            content.decode("utf-8")
            binary = b"\0" in content
        except UnicodeError:
            binary = True
        commands.append(
            {
                "kind": "create",
                "file_id": str(uuid5(project_id, f"{key}:{name}")),
                "path": name,
                "content_base64": encode(content),
                "binary": binary,
                "executable": mode == "100755",
            }
        )
    instance.change(
        epoch=1,
        expected_sequence=0,
        key=f"conversion:{uuid5(project_id, key)}",
        commands=commands,
        kind="conversion",
        owner=True,
        converting=True,
    )
    instance.checkpoint(
        "Converted from Git", identifier=uuid5(project_id, "conversion-checkpoint"), converting=True
    )
    with instance.git.locked():
        instance.authorize(True, True, converting=True)
        project = db.get(SqlProject, project_id)
        receipt = db.get(SqlLinearConversion, project_id)
        assert project is not None and receipt is not None
        project.workspace_mode, receipt.completed = "linear", True
        db.commit()

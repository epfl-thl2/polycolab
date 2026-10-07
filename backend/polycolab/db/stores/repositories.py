"""Repository metadata adapter; Git contents stay outside SQL."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.errors import persistence_boundary
from polycolab.db.models import SqlAgentRun, SqlAgentSession, SqlRunWriteGrant
from polycolab.db.models.repositories import (
    SqlRepositoryMutation,
    SqlRepositoryRun,
    SqlRepositorySession,
    SqlWorkspaceRepository,
)
from polycolab.db.models.workspace_tasks import SqlWorkspaceTask
from polycolab.entities.repositories import (
    RepositoryError,
    RepositoryReceipt,
    RepositoryRun,
    RepositorySession,
    WorkspaceTask,
)
from polycolab.entities.time import utc_now


def task_snapshot(row: SqlWorkspaceTask) -> WorkspaceTask:
    return WorkspaceTask(
        row.id,
        row.workspace_id,
        row.title,
        row.branch,
        row.created_by_user_id,
        row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at,
        row.updated_at.replace(tzinfo=UTC) if row.updated_at.tzinfo is None else row.updated_at,
        row.archived_at.replace(tzinfo=UTC)
        if row.archived_at is not None and row.archived_at.tzinfo is None
        else row.archived_at,
    )


def snapshot(row: SqlRepositoryMutation) -> RepositoryReceipt:
    return RepositoryReceipt(
        row.id,
        row.workspace_id,
        row.user_id,
        row.key,
        row.digest,
        row.branch,
        row.old_commit,
        row.new_commit,
        row.completed,
        row.created_at,
    )


class SqlRepositoryStore:
    def __init__(self, session: Session):
        self.db = session

    @persistence_boundary
    def registered(self, workspace_id: UUID) -> bool:
        return self.db.get(SqlWorkspaceRepository, workspace_id) is not None

    @persistence_boundary
    def register(self, workspace_id: UUID) -> None:
        if self.db.get(SqlWorkspaceRepository, workspace_id) is None:
            self.db.add(SqlWorkspaceRepository(workspace_id=workspace_id))
            self.db.flush()

    @persistence_boundary
    def receipt(self, workspace_id: UUID, user_id: UUID, key: str) -> RepositoryReceipt | None:
        row = self.db.scalar(
            select(SqlRepositoryMutation).where(
                SqlRepositoryMutation.workspace_id == workspace_id,
                SqlRepositoryMutation.user_id == user_id,
                SqlRepositoryMutation.key == key,
            )
        )
        return snapshot(row) if row else None

    @persistence_boundary
    def prepare(self, receipt: RepositoryReceipt) -> None:
        self.db.add(
            SqlRepositoryMutation(
                **{name: getattr(receipt, name) for name in receipt.__dataclass_fields__}
            )
        )
        self.db.flush()

    @persistence_boundary
    def complete(self, receipt_id: UUID) -> None:
        row = self.db.get(SqlRepositoryMutation, receipt_id)
        assert row is not None
        row.completed = True
        self.db.flush()

    @persistence_boundary
    def pending(self, workspace_id: UUID) -> tuple[RepositoryReceipt, ...]:
        return tuple(
            snapshot(row)
            for row in self.db.scalars(
                select(SqlRepositoryMutation)
                .where(
                    SqlRepositoryMutation.workspace_id == workspace_id,
                    SqlRepositoryMutation.completed.is_(False),
                )
                .limit(100)
            )
        )

    @persistence_boundary
    def session_active(self, workspace_id: UUID, session_id: UUID) -> bool:
        row = self.db.get(SqlAgentSession, session_id)
        if row is None or row.project_id != workspace_id:
            raise RepositoryError("repository_branch_not_found", 404)
        return (
            self.db.scalar(
                select(SqlAgentRun.id)
                .where(
                    SqlAgentRun.session_id == session_id,
                    SqlAgentRun.status.in_(["QUEUED", "CLAIMED", "RUNNING", "CANCELLING"]),
                )
                .limit(1)
            )
            is not None
        )

    @persistence_boundary
    def session(self, workspace_id: UUID, session_id: UUID) -> RepositorySession:
        row = self.db.get(SqlAgentSession, session_id)
        if row is None or row.project_id != workspace_id:
            raise RepositoryError("repository_session_not_found", 404)
        return RepositorySession(
            session_id,
            workspace_id,
            row.created_by_user_id,
            row.task_id is not None or self.db.get(SqlRepositorySession, session_id) is not None,
            self.session_active(workspace_id, session_id),
            self.task(workspace_id, row.task_id).branch
            if row.task_id
            else f"sessions/{session_id}",
        )

    @persistence_boundary
    def enable_session(self, workspace_id: UUID, session_id: UUID, commit: str) -> None:
        if self.db.get(SqlRepositorySession, session_id) is None:
            self.db.add(
                SqlRepositorySession(
                    session_id=session_id, workspace_id=workspace_id, base_commit=commit
                )
            )
            self.db.flush()

    @persistence_boundary
    def run(self, run_id: UUID) -> RepositoryRun | None:
        row = self.db.get(SqlRepositoryRun, run_id)
        return (
            RepositoryRun(
                row.run_id,
                row.session_id,
                row.input_commit,
                row.output_commit,
                row.branch or f"sessions/{row.session_id}",
            )
            if row
            else None
        )

    @persistence_boundary
    def pin_run(self, run_id: UUID, session_id: UUID, commit: str, branch: str) -> None:
        self.db.add(
            SqlRepositoryRun(
                run_id=run_id, session_id=session_id, input_commit=commit, branch=branch
            )
        )
        self.db.flush()

    @persistence_boundary
    def finish_run(self, run_id: UUID, commit: str) -> None:
        row = self.db.get(SqlRepositoryRun, run_id)
        assert row is not None
        row.output_commit = commit
        self.db.flush()

    @persistence_boundary
    def public_run(self, run_id: UUID) -> bool:
        grant = self.db.get(SqlRunWriteGrant, run_id)
        return grant is not None and grant.request.get("destination") == "PUBLIC"

    @persistence_boundary
    def task(self, workspace_id: UUID, task_id: UUID, *, lock: bool = False) -> WorkspaceTask:
        query = select(SqlWorkspaceTask).where(
            SqlWorkspaceTask.id == task_id, SqlWorkspaceTask.workspace_id == workspace_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.db.scalar(query)
        if row is None:
            raise RepositoryError("workspace_task_not_found", 404)
        return task_snapshot(row)

    @persistence_boundary
    def tasks(self, workspace_id: UUID, include_archived: bool) -> list[WorkspaceTask]:
        query = select(SqlWorkspaceTask).where(SqlWorkspaceTask.workspace_id == workspace_id)
        if not include_archived:
            query = query.where(SqlWorkspaceTask.archived_at.is_(None))
        return [
            task_snapshot(row)
            for row in self.db.scalars(
                query.order_by(SqlWorkspaceTask.updated_at.desc(), SqlWorkspaceTask.id.desc())
            )
        ]

    @persistence_boundary
    def create_task(self, task: WorkspaceTask) -> None:
        self.db.add(
            SqlWorkspaceTask(**{name: getattr(task, name) for name in task.__dataclass_fields__})
        )
        self.db.flush()

    @persistence_boundary
    def update_task(self, task_id: UUID, title: str | None, archived: bool | None) -> WorkspaceTask:
        row = self.db.get(SqlWorkspaceTask, task_id)
        assert row is not None
        if title is not None:
            row.title = title
        if archived is not None:
            row.archived_at = utc_now() if archived else None
        row.updated_at = utc_now()
        self.db.flush()
        return task_snapshot(row)

    @persistence_boundary
    def branch_active(self, workspace_id: UUID, branch: str) -> bool:
        task = self.db.scalar(
            select(SqlWorkspaceTask).where(
                SqlWorkspaceTask.workspace_id == workspace_id, SqlWorkspaceTask.branch == branch
            )
        )
        if task is None:
            return (
                self.session_active(workspace_id, UUID(branch[9:]))
                if branch.startswith("sessions/")
                else False
            )
        return (
            self.db.scalar(
                select(SqlAgentRun.id)
                .join(SqlAgentSession, SqlAgentSession.id == SqlAgentRun.session_id)
                .where(
                    SqlAgentSession.task_id == task.id,
                    SqlAgentRun.status.in_(["QUEUED", "CLAIMED", "RUNNING", "CANCELLING"]),
                )
                .limit(1)
            )
            is not None
        )

    @persistence_boundary
    def branch_archived(self, workspace_id: UUID, branch: str) -> bool:
        return (
            self.db.scalar(
                select(SqlWorkspaceTask.id).where(
                    SqlWorkspaceTask.workspace_id == workspace_id,
                    SqlWorkspaceTask.branch == branch,
                    SqlWorkspaceTask.archived_at.is_not(None),
                )
            )
            is not None
        )

    @persistence_boundary
    def lock_branch(self, workspace_id: UUID, branch: str) -> None:
        self.db.scalar(
            select(SqlWorkspaceTask.id)
            .where(SqlWorkspaceTask.workspace_id == workspace_id, SqlWorkspaceTask.branch == branch)
            .with_for_update()
        )

    @persistence_boundary
    def task_identifier_taken(self, task_id: UUID) -> bool:
        return self.db.get(SqlWorkspaceTask, task_id) is not None

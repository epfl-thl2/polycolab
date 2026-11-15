"""Repository metadata adapter; Git contents stay outside SQL."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from polycolab.db.errors import persistence_boundary
from polycolab.db.models import SqlAgentRun, SqlConversation
from polycolab.db.models.repositories import (
    SqlProjectRepository,
    SqlRepositoryConversation,
    SqlRepositoryIdempotencyRecord,
    SqlRepositoryRun,
)
from polycolab.db.models.worktrees import SqlWorktree
from polycolab.entities.repositories import (
    RepositoryConversation,
    RepositoryError,
    RepositoryIdempotencyRecord,
    RepositoryRun,
    Worktree,
)
from polycolab.entities.time import utc_now


def worktree_snapshot(row: SqlWorktree) -> Worktree:
    return Worktree(
        row.id,
        row.project_id,
        row.title,
        row.branch,
        row.created_by_user_id,
        row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at,
        row.updated_at.replace(tzinfo=UTC) if row.updated_at.tzinfo is None else row.updated_at,
        row.removed_at.replace(tzinfo=UTC)
        if row.removed_at is not None and row.removed_at.tzinfo is None
        else row.removed_at,
    )


def snapshot(row: SqlRepositoryIdempotencyRecord) -> RepositoryIdempotencyRecord:
    return RepositoryIdempotencyRecord(
        row.id,
        row.project_id,
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
    def project_active(self, project_id: UUID) -> bool:
        return (
            self.db.scalar(
                select(SqlAgentRun.id)
                .where(
                    SqlAgentRun.project_id == project_id,
                    SqlAgentRun.status.in_(["QUEUED", "CLAIMED", "RUNNING", "CANCELLING"]),
                )
                .limit(1)
            )
            is not None
        )

    @persistence_boundary
    def native(self, project_id: UUID) -> bool:
        row = self.db.get(SqlProjectRepository, project_id)
        return bool(row and row.native_worktrees)

    @persistence_boundary
    def activate_native(self, project_id: UUID) -> None:
        row = self.db.get(SqlProjectRepository, project_id)
        assert row is not None
        for worktree in self.worktrees(project_id, True):
            if worktree.branch.startswith("sessions/"):
                self.db.execute(
                    update(SqlConversation)
                    .where(
                        SqlConversation.project_id == project_id,
                        SqlConversation.id == UUID(worktree.branch[9:]),
                        SqlConversation.worktree_id.is_(None),
                    )
                    .values(worktree_id=worktree.id)
                )
        main_id = self.db.scalar(
            select(SqlWorktree.id).where(
                SqlWorktree.project_id == project_id, SqlWorktree.branch == "main"
            )
        )
        self.db.execute(
            update(SqlConversation)
            .where(SqlConversation.project_id == project_id, SqlConversation.worktree_id.is_(None))
            .values(worktree_id=main_id)
        )
        row.native_worktrees = True
        self.db.flush()

    @persistence_boundary
    def registered(self, project_id: UUID) -> bool:
        return self.db.get(SqlProjectRepository, project_id) is not None

    @persistence_boundary
    def register(self, project_id: UUID) -> None:
        if self.db.get(SqlProjectRepository, project_id) is None:
            self.db.add(SqlProjectRepository(project_id=project_id))
            self.db.flush()

    @persistence_boundary
    def record(
        self, project_id: UUID, user_id: UUID, key: str
    ) -> RepositoryIdempotencyRecord | None:
        row = self.db.scalar(
            select(SqlRepositoryIdempotencyRecord).where(
                SqlRepositoryIdempotencyRecord.project_id == project_id,
                SqlRepositoryIdempotencyRecord.user_id == user_id,
                SqlRepositoryIdempotencyRecord.key == key,
            )
        )
        return snapshot(row) if row else None

    @persistence_boundary
    def prepare(self, record: RepositoryIdempotencyRecord) -> None:
        self.db.add(
            SqlRepositoryIdempotencyRecord(
                **{name: getattr(record, name) for name in record.__dataclass_fields__}
            )
        )
        self.db.flush()

    @persistence_boundary
    def complete(self, record_id: UUID) -> None:
        row = self.db.get(SqlRepositoryIdempotencyRecord, record_id)
        assert row is not None
        row.completed = True
        self.db.flush()

    @persistence_boundary
    def pending(self, project_id: UUID) -> tuple[RepositoryIdempotencyRecord, ...]:
        return tuple(
            snapshot(row)
            for row in self.db.scalars(
                select(SqlRepositoryIdempotencyRecord)
                .where(
                    SqlRepositoryIdempotencyRecord.project_id == project_id,
                    SqlRepositoryIdempotencyRecord.completed.is_(False),
                )
                .limit(100)
            )
        )

    @persistence_boundary
    def conversation_active(self, project_id: UUID, conversation_id: UUID) -> bool:
        row = self.db.get(SqlConversation, conversation_id)
        if row is None or row.project_id != project_id:
            raise RepositoryError("repository_branch_not_found", 404)
        return (
            self.db.scalar(
                select(SqlAgentRun.id)
                .where(
                    SqlAgentRun.conversation_id == conversation_id,
                    SqlAgentRun.status.in_(["QUEUED", "CLAIMED", "RUNNING", "CANCELLING"]),
                )
                .limit(1)
            )
            is not None
        )

    @persistence_boundary
    def conversation(self, project_id: UUID, conversation_id: UUID) -> RepositoryConversation:
        row = self.db.get(SqlConversation, conversation_id)
        if row is None or row.project_id != project_id:
            raise RepositoryError("repository_conversation_not_found", 404)
        return RepositoryConversation(
            conversation_id,
            project_id,
            row.created_by_user_id,
            row.worktree_id is not None
            or self.db.get(SqlRepositoryConversation, conversation_id) is not None,
            self.conversation_active(project_id, conversation_id),
            self.worktree(project_id, row.worktree_id).branch
            if row.worktree_id
            else f"sessions/{conversation_id}",
        )

    @persistence_boundary
    def enable_conversation(self, project_id: UUID, conversation_id: UUID, commit: str) -> None:
        if self.db.get(SqlRepositoryConversation, conversation_id) is None:
            self.db.add(
                SqlRepositoryConversation(
                    conversation_id=conversation_id, project_id=project_id, base_commit=commit
                )
            )
            self.db.flush()

    @persistence_boundary
    def run(self, run_id: UUID) -> RepositoryRun | None:
        row = self.db.get(SqlRepositoryRun, run_id)
        return (
            RepositoryRun(
                row.run_id,
                row.conversation_id,
                row.input_commit,
                row.output_commit,
                row.branch or f"sessions/{row.conversation_id}",
                row.input_revision,
                row.worktree_id,
            )
            if row
            else None
        )

    @persistence_boundary
    def pin_run(
        self,
        run_id: UUID,
        conversation_id: UUID,
        commit: str,
        branch: str,
        revision: str | None = None,
        worktree_id: UUID | None = None,
    ) -> None:
        self.db.add(
            SqlRepositoryRun(
                run_id=run_id,
                conversation_id=conversation_id,
                input_commit=commit,
                branch=branch,
                input_revision=revision,
                worktree_id=worktree_id,
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
    def worktree(self, project_id: UUID, worktree_id: UUID, *, lock: bool = False) -> Worktree:
        query = select(SqlWorktree).where(
            SqlWorktree.id == worktree_id, SqlWorktree.project_id == project_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = self.db.scalar(query)
        if row is None:
            raise RepositoryError("worktree_not_found", 404)
        return worktree_snapshot(row)

    @persistence_boundary
    def worktrees(self, project_id: UUID, include_removed: bool) -> list[Worktree]:
        query = select(SqlWorktree).where(SqlWorktree.project_id == project_id)
        if not include_removed:
            query = query.where(SqlWorktree.removed_at.is_(None))
        return [
            worktree_snapshot(row)
            for row in self.db.scalars(
                query.order_by(SqlWorktree.updated_at.desc(), SqlWorktree.id.desc())
            )
        ]

    @persistence_boundary
    def create_worktree(self, worktree: Worktree) -> None:
        self.db.add(
            SqlWorktree(**{name: getattr(worktree, name) for name in worktree.__dataclass_fields__})
        )
        self.db.flush()

    @persistence_boundary
    def update_worktree(
        self, worktree_id: UUID, title: str | None, removed: bool | None
    ) -> Worktree:
        row = self.db.get(SqlWorktree, worktree_id)
        assert row is not None
        if title is not None:
            row.title = title
        if removed is not None:
            row.removed_at = utc_now() if removed else None
        row.updated_at = utc_now()
        self.db.flush()
        return worktree_snapshot(row)

    @persistence_boundary
    def branch_active(self, project_id: UUID, branch: str) -> bool:
        worktree = self.db.scalar(
            select(SqlWorktree).where(
                SqlWorktree.project_id == project_id, SqlWorktree.branch == branch
            )
        )
        if worktree is None:
            return (
                self.conversation_active(project_id, UUID(branch[9:]))
                if branch.startswith("sessions/")
                else False
            )
        return (
            self.db.scalar(
                select(SqlAgentRun.id)
                .join(SqlConversation, SqlConversation.id == SqlAgentRun.conversation_id)
                .where(
                    SqlConversation.worktree_id == worktree.id,
                    SqlAgentRun.status.in_(["QUEUED", "CLAIMED", "RUNNING", "CANCELLING"]),
                )
                .limit(1)
            )
            is not None
        )

    @persistence_boundary
    def branch_removed(self, project_id: UUID, branch: str) -> bool:
        return (
            self.db.scalar(
                select(SqlWorktree.id).where(
                    SqlWorktree.project_id == project_id,
                    SqlWorktree.branch == branch,
                    SqlWorktree.removed_at.is_not(None),
                )
            )
            is not None
        )

    @persistence_boundary
    def lock_branch(self, project_id: UUID, branch: str) -> None:
        self.db.scalar(
            select(SqlWorktree.id)
            .where(SqlWorktree.project_id == project_id, SqlWorktree.branch == branch)
            .with_for_update()
        )

    @persistence_boundary
    def worktree_identifier_taken(self, worktree_id: UUID) -> bool:
        return self.db.get(SqlWorktree, worktree_id) is not None

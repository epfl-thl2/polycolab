"""SQL adapter for committed collaborative workspace state."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from polycolab.db.converters.time import timestamp
from polycolab.db.models.collaborative import (
    SqlCollaborativeCheckpoint,
    SqlCollaborativeConversion,
    SqlCollaborativeFile,
    SqlCollaborativeOperation,
    SqlCollaborativeWorkspace,
)
from polycolab.entities.collaborative import (
    CollaborativeCheckpoint,
    CollaborativeFile,
    CollaborativeOperation,
    CollaborativeState,
)
from polycolab.entities.repositories import RepositoryError


def operation(row: SqlCollaborativeOperation) -> CollaborativeOperation:
    return CollaborativeOperation(
        row.project_id,
        row.sequence,
        row.epoch,
        row.user_id,
        row.request_key,
        row.digest,
        row.kind,
        row.payload,
        timestamp(row.created_at),
    )


def checkpoint(row: SqlCollaborativeCheckpoint) -> CollaborativeCheckpoint:
    return CollaborativeCheckpoint(
        row.id,
        row.project_id,
        row.sequence,
        row.epoch,
        row.title,
        row.tree,
        row.files,
        timestamp(row.created_at),
    )


class SqlCollaborativeStore:
    def __init__(self, session: Session):
        self.db = session

    def begin_write(self, project_id: UUID) -> None:
        # SQLite cannot upgrade a read snapshot after another connection commits.
        # Acquire its writer reservation before any reads in this transaction.
        if self.db.get_bind().dialect.name == "sqlite":
            self.db.execute(
                update(SqlCollaborativeWorkspace)
                .where(SqlCollaborativeWorkspace.project_id == project_id)
                .values(sequence=SqlCollaborativeWorkspace.sequence)
            )

    def has_archive(self, project_id: UUID) -> bool:
        row = self.db.get(SqlCollaborativeConversion, project_id, populate_existing=True)
        return row is not None and row.completed

    def conversion_pending(self, project_id: UUID) -> bool:
        row = self.db.get(SqlCollaborativeConversion, project_id, populate_existing=True)
        return row is not None and not row.completed

    def state(self, project_id: UUID) -> CollaborativeState | None:
        row = self.db.get(SqlCollaborativeWorkspace, project_id, populate_existing=True)
        if row is None:
            return None
        files = tuple(
            CollaborativeFile(f.id, f.path, f.content, f.document, f.executable, f.deleted)
            for f in self.db.scalars(
                select(SqlCollaborativeFile)
                .where(SqlCollaborativeFile.project_id == project_id)
                .execution_options(populate_existing=True)
            )
        )
        return CollaborativeState(project_id, row.epoch, row.sequence, row.stored_bytes, files)

    def initialize(self, project_id: UUID) -> None:
        if self.db.get(SqlCollaborativeWorkspace, project_id) is None:
            self.db.add(SqlCollaborativeWorkspace(project_id=project_id))
            self.db.flush()

    def record(self, project_id: UUID, user_id: UUID, key: str) -> CollaborativeOperation | None:
        row = self.db.scalar(
            select(SqlCollaborativeOperation).where(
                SqlCollaborativeOperation.project_id == project_id,
                SqlCollaborativeOperation.user_id == user_id,
                SqlCollaborativeOperation.request_key == key,
            )
        )
        return operation(row) if row else None

    def operations(
        self, project_id: UUID, after: int, limit: int = 100
    ) -> list[CollaborativeOperation]:
        return [
            operation(row)
            for row in self.db.scalars(
                select(SqlCollaborativeOperation)
                .where(
                    SqlCollaborativeOperation.project_id == project_id,
                    SqlCollaborativeOperation.sequence > after,
                )
                .order_by(SqlCollaborativeOperation.sequence)
                .limit(limit)
            )
        ]

    def accept(
        self,
        previous: CollaborativeState,
        value: CollaborativeOperation,
        files: list[CollaborativeFile],
        stored_bytes: int,
    ) -> None:
        result = self.db.execute(
            update(SqlCollaborativeWorkspace)
            .where(
                SqlCollaborativeWorkspace.project_id == previous.project_id,
                SqlCollaborativeWorkspace.sequence == previous.sequence,
                SqlCollaborativeWorkspace.epoch == previous.epoch,
            )
            .values(sequence=value.sequence, epoch=value.epoch, stored_bytes=stored_bytes)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise RepositoryError("collaborative_stale_revision")
        for file in files:
            row = self.db.get(SqlCollaborativeFile, file.id)
            if row is None:
                row = SqlCollaborativeFile(id=file.id, project_id=previous.project_id)
                self.db.add(row)
            elif row.project_id != previous.project_id:
                raise RepositoryError("collaborative_file_not_found", 404)
            row.path, row.content, row.document = file.path, file.content, file.document
            row.executable, row.deleted = file.executable, file.deleted
        self.db.add(
            SqlCollaborativeOperation(
                project_id=value.project_id,
                sequence=value.sequence,
                epoch=value.epoch,
                user_id=value.user_id,
                request_key=value.key,
                digest=value.digest,
                kind=value.kind,
                payload=value.payload,
                created_at=value.created_at,
            )
        )
        self.db.flush()

    def checkpoints(self, project_id: UUID) -> list[CollaborativeCheckpoint]:
        return [
            checkpoint(row)
            for row in self.db.scalars(
                select(SqlCollaborativeCheckpoint)
                .where(SqlCollaborativeCheckpoint.project_id == project_id)
                .order_by(
                    SqlCollaborativeCheckpoint.sequence.desc(),
                    SqlCollaborativeCheckpoint.created_at.desc(),
                )
                .limit(100)
            )
        ]

    def checkpoint(self, project_id: UUID, identifier: UUID) -> CollaborativeCheckpoint | None:
        row = self.db.get(SqlCollaborativeCheckpoint, identifier)
        return checkpoint(row) if row and row.project_id == project_id else None

    def add_storage(self, project_id: UUID, byte_count: int) -> None:
        self.db.execute(
            update(SqlCollaborativeWorkspace)
            .where(SqlCollaborativeWorkspace.project_id == project_id)
            .values(stored_bytes=SqlCollaborativeWorkspace.stored_bytes + byte_count)
        )

    def add_checkpoint(self, value: CollaborativeCheckpoint) -> None:
        self.db.add(
            SqlCollaborativeCheckpoint(
                id=value.id,
                project_id=value.project_id,
                sequence=value.sequence,
                epoch=value.epoch,
                title=value.title,
                tree=value.tree,
                files=value.files,
                created_at=value.created_at,
            )
        )
        self.db.flush()

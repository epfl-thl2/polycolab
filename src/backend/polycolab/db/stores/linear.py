"""SQL adapter for committed linear workspace state."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from polycolab.db.converters.time import timestamp
from polycolab.db.models.linear import (
    SqlLinearCheckpoint,
    SqlLinearConversion,
    SqlLinearFile,
    SqlLinearOperation,
    SqlLinearWorkspace,
)
from polycolab.entities.linear import LinearCheckpoint, LinearFile, LinearOperation, LinearState
from polycolab.entities.repositories import RepositoryError


def operation(row: SqlLinearOperation) -> LinearOperation:
    return LinearOperation(
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


def checkpoint(row: SqlLinearCheckpoint) -> LinearCheckpoint:
    return LinearCheckpoint(
        row.id,
        row.project_id,
        row.sequence,
        row.epoch,
        row.title,
        row.tree,
        row.files,
        timestamp(row.created_at),
    )


class SqlLinearStore:
    def __init__(self, session: Session):
        self.db = session

    def begin_write(self, project_id: UUID) -> None:
        # SQLite cannot upgrade a read snapshot after another connection commits.
        # Acquire its writer reservation before any reads in this transaction.
        if self.db.get_bind().dialect.name == "sqlite":
            self.db.execute(
                update(SqlLinearWorkspace)
                .where(SqlLinearWorkspace.project_id == project_id)
                .values(sequence=SqlLinearWorkspace.sequence)
            )

    def has_archive(self, project_id: UUID) -> bool:
        row = self.db.get(SqlLinearConversion, project_id, populate_existing=True)
        return row is not None and row.completed

    def conversion_pending(self, project_id: UUID) -> bool:
        row = self.db.get(SqlLinearConversion, project_id, populate_existing=True)
        return row is not None and not row.completed

    def state(self, project_id: UUID) -> LinearState | None:
        row = self.db.get(SqlLinearWorkspace, project_id, populate_existing=True)
        if row is None:
            return None
        files = tuple(
            LinearFile(f.id, f.path, f.content, f.document, f.executable, f.deleted)
            for f in self.db.scalars(
                select(SqlLinearFile)
                .where(SqlLinearFile.project_id == project_id)
                .execution_options(populate_existing=True)
            )
        )
        return LinearState(project_id, row.epoch, row.sequence, row.stored_bytes, files)

    def initialize(self, project_id: UUID) -> None:
        if self.db.get(SqlLinearWorkspace, project_id) is None:
            self.db.add(SqlLinearWorkspace(project_id=project_id))
            self.db.flush()

    def receipt(self, project_id: UUID, user_id: UUID, key: str) -> LinearOperation | None:
        row = self.db.scalar(
            select(SqlLinearOperation).where(
                SqlLinearOperation.project_id == project_id,
                SqlLinearOperation.user_id == user_id,
                SqlLinearOperation.request_key == key,
            )
        )
        return operation(row) if row else None

    def operations(self, project_id: UUID, after: int, limit: int = 100) -> list[LinearOperation]:
        return [
            operation(row)
            for row in self.db.scalars(
                select(SqlLinearOperation)
                .where(
                    SqlLinearOperation.project_id == project_id, SqlLinearOperation.sequence > after
                )
                .order_by(SqlLinearOperation.sequence)
                .limit(limit)
            )
        ]

    def accept(
        self,
        previous: LinearState,
        value: LinearOperation,
        files: list[LinearFile],
        stored_bytes: int,
    ) -> None:
        result = self.db.execute(
            update(SqlLinearWorkspace)
            .where(
                SqlLinearWorkspace.project_id == previous.project_id,
                SqlLinearWorkspace.sequence == previous.sequence,
                SqlLinearWorkspace.epoch == previous.epoch,
            )
            .values(sequence=value.sequence, epoch=value.epoch, stored_bytes=stored_bytes)
        )
        if cast(CursorResult[Any], result).rowcount != 1:
            raise RepositoryError("linear_stale_revision")
        for file in files:
            row = self.db.get(SqlLinearFile, file.id)
            if row is None:
                row = SqlLinearFile(id=file.id, project_id=previous.project_id)
                self.db.add(row)
            elif row.project_id != previous.project_id:
                raise RepositoryError("linear_file_not_found", 404)
            row.path, row.content, row.document = file.path, file.content, file.document
            row.executable, row.deleted = file.executable, file.deleted
        self.db.add(
            SqlLinearOperation(
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

    def checkpoints(self, project_id: UUID) -> list[LinearCheckpoint]:
        return [
            checkpoint(row)
            for row in self.db.scalars(
                select(SqlLinearCheckpoint)
                .where(SqlLinearCheckpoint.project_id == project_id)
                .order_by(
                    SqlLinearCheckpoint.sequence.desc(), SqlLinearCheckpoint.created_at.desc()
                )
                .limit(100)
            )
        ]

    def checkpoint(self, project_id: UUID, identifier: UUID) -> LinearCheckpoint | None:
        row = self.db.get(SqlLinearCheckpoint, identifier)
        return checkpoint(row) if row and row.project_id == project_id else None

    def add_storage(self, project_id: UUID, byte_count: int) -> None:
        self.db.execute(
            update(SqlLinearWorkspace)
            .where(SqlLinearWorkspace.project_id == project_id)
            .values(stored_bytes=SqlLinearWorkspace.stored_bytes + byte_count)
        )

    def add_checkpoint(self, value: LinearCheckpoint) -> None:
        self.db.add(
            SqlLinearCheckpoint(
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

"""SQL statements and queue serialization for document compilation."""

from dataclasses import asdict
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import String, and_, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from polycolab.db.converters.time import timestamp
from polycolab.db.errors import persistence_boundary
from polycolab.db.models.document_builds import SqlDocumentBuild, SqlDocumentBuildQueue
from polycolab.db.models.project_tasks import SqlProjectTask
from polycolab.entities.document_builds import ACTIVE, BuildBlob, BuildStatus, DocumentBuild, Engine


def blob(value: dict[str, object]) -> BuildBlob:
    return BuildBlob(
        str(value["key"]),
        str(value["sha256"]),
        int(cast(int, value["byte_length"])),
        bool(value["verified"]),
    )


def entity(row: SqlDocumentBuild) -> DocumentBuild:
    return DocumentBuild(
        row.id,
        row.project_id,
        row.worktree_id,
        row.requested_by,
        row.request_key,
        row.revision,
        row.main_file,
        cast(Engine, row.engine),
        row.image,
        cast(BuildStatus, row.status),
        timestamp(row.created_at),
        timestamp(row.expires_at),
        blob(row.input),
        {kind: blob(value) for kind, value in row.outputs.items()},
        row.generation,
        row.worker_id,
        timestamp(row.lease_until),
        timestamp(row.deadline),
        timestamp(row.physical_until),
        row.error,
    )


class SqlBuildStore:
    def __init__(self, session: Session):
        self.session = session

    @persistence_boundary
    def lock_queue(self) -> tuple[datetime | None, str | None]:
        insert = sqlite_insert if self.session.get_bind().dialect.name == "sqlite" else pg_insert
        self.session.execute(
            insert(SqlDocumentBuildQueue).values(id=1, generation=0).on_conflict_do_nothing()
        )
        self.session.execute(
            update(SqlDocumentBuildQueue)
            .where(SqlDocumentBuildQueue.id == 1)
            .values(generation=SqlDocumentBuildQueue.generation + 1)
        )
        row = self.session.get(SqlDocumentBuildQueue, 1, populate_existing=True)
        assert row is not None
        return timestamp(row.ready_until), row.image

    @persistence_boundary
    def ready(self, image: str, until: datetime) -> None:
        self.session.execute(
            update(SqlDocumentBuildQueue)
            .where(SqlDocumentBuildQueue.id == 1)
            .values(image=image, ready_until=until)
        )

    @persistence_boundary
    def get(self, identifier: UUID) -> DocumentBuild | None:
        row = self.session.get(SqlDocumentBuild, identifier, populate_existing=True)
        return entity(row) if row else None

    @persistence_boundary
    def recent(self, project: UUID, worktree: UUID, now: datetime) -> list[DocumentBuild]:
        query = (
            select(SqlDocumentBuild)
            .where(
                SqlDocumentBuild.project_id == project,
                SqlDocumentBuild.worktree_id == worktree,
                SqlDocumentBuild.expires_at > now,
            )
            .order_by(SqlDocumentBuild.created_at.desc(), SqlDocumentBuild.id)
        )
        rows = list(self.session.scalars(query.limit(50)))
        # Failed attempts must not hide the last retained successful PDF.
        success = self.session.scalar(query.where(SqlDocumentBuild.status == "succeeded").limit(1))
        if success and all(row.id != success.id for row in rows):
            rows.append(success)
        return [entity(row) for row in rows]

    @persistence_boundary
    def retry(self, project: UUID, worktree: UUID, user: UUID, key: str) -> DocumentBuild | None:
        row = self.session.scalar(
            select(SqlDocumentBuild).where(
                SqlDocumentBuild.project_id == project,
                SqlDocumentBuild.worktree_id == worktree,
                SqlDocumentBuild.requested_by == user,
                SqlDocumentBuild.request_key == key,
            )
        )
        return entity(row) if row else None

    @persistence_boundary
    def create(self, build: DocumentBuild) -> None:
        self.session.add(SqlDocumentBuild(**asdict(build)))
        self.session.flush()

    @persistence_boundary
    def pending(self, project: UUID | None = None) -> list[DocumentBuild]:
        return [
            entity(row)
            for row in self.session.scalars(
                select(SqlDocumentBuild)
                .where(
                    SqlDocumentBuild.status.in_(ACTIVE),
                    SqlDocumentBuild.project_id == project if project is not None else true(),
                )
                .order_by(SqlDocumentBuild.created_at, SqlDocumentBuild.id)
                .limit(1000)
            )
        ]

    @persistence_boundary
    def occupied(self, now: datetime) -> list[DocumentBuild]:
        return [
            entity(row)
            for row in self.session.scalars(
                select(SqlDocumentBuild).where(SqlDocumentBuild.physical_until > now)
            )
        ]

    @persistence_boundary
    def project_usage(self, project: UUID) -> int:
        return sum(
            sum(
                int(cast(int, value["byte_length"]))
                for value in (row.input, *row.outputs.values())
                if value["key"]
            )
            for row in self.session.scalars(
                select(SqlDocumentBuild).where(SqlDocumentBuild.project_id == project)
            )
        )

    @persistence_boundary
    def state(self, identifier: UUID, status: BuildStatus, error: str | None = None) -> None:
        self.session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == identifier)
            .values(status=status, error=error)
        )

    @persistence_boundary
    def claim(
        self,
        identifier: UUID,
        worker: str,
        generation: UUID,
        lease: datetime,
        deadline: datetime,
        physical: datetime,
    ) -> None:
        self.session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == identifier)
            .values(
                status="running",
                worker_id=worker,
                generation=generation,
                lease_until=lease,
                deadline=deadline,
                physical_until=physical,
            )
        )

    @persistence_boundary
    def heartbeat(self, identifier: UUID, until: datetime) -> None:
        self.session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == identifier)
            .values(lease_until=until)
        )

    @persistence_boundary
    def release(self, identifier: UUID) -> None:
        self.session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == identifier)
            .values(physical_until=None)
        )

    @persistence_boundary
    def output(self, identifier: UUID, kind: str, value: BuildBlob) -> None:
        row = self.session.get(SqlDocumentBuild, identifier, populate_existing=True)
        assert row is not None
        self.session.execute(
            update(SqlDocumentBuild)
            .where(SqlDocumentBuild.id == identifier)
            .values(outputs={**row.outputs, kind: asdict(value)})
        )

    @persistence_boundary
    def cleanup_candidates(self, now: datetime) -> list[DocumentBuild]:
        return [
            entity(row)
            for row in self.session.scalars(
                select(SqlDocumentBuild)
                .where(
                    SqlDocumentBuild.status.not_in(ACTIVE),
                    or_(
                        SqlDocumentBuild.input["key"].as_string() != "",
                        and_(
                            SqlDocumentBuild.expires_at <= now,
                            SqlDocumentBuild.outputs.cast(String) != "{}",
                        ),
                    ),
                    or_(
                        SqlDocumentBuild.physical_until.is_(None),
                        SqlDocumentBuild.physical_until < now,
                    ),
                )
                .order_by(SqlDocumentBuild.created_at)
                .limit(1000)
            )
        ]

    @persistence_boundary
    def forget_blob(self, identifier: UUID, kind: str) -> None:
        row = self.session.get(SqlDocumentBuild, identifier, populate_existing=True)
        assert row is not None
        if kind == "input":
            self.session.execute(
                update(SqlDocumentBuild)
                .where(SqlDocumentBuild.id == identifier)
                .values(input={**row.input, "key": ""})
            )
        else:
            self.session.execute(
                update(SqlDocumentBuild)
                .where(SqlDocumentBuild.id == identifier)
                .values(outputs={key: value for key, value in row.outputs.items() if key != kind})
            )

    @persistence_boundary
    def worktree_available(self, project: UUID, worktree: UUID) -> bool:
        return (
            self.session.scalar(
                select(SqlProjectTask.id).where(
                    SqlProjectTask.id == worktree,
                    SqlProjectTask.project_id == project,
                    SqlProjectTask.archived_at.is_(None),
                )
            )
            is not None
        )

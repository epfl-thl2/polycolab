"""SQL reads and writes for artifact cleanup, without lifecycle policy."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from polycolab.db.converters.artifacts import artifact
from polycolab.db.errors import persistence_boundary
from polycolab.db.models import SqlArtifact
from polycolab.entities.artifacts import StoredArtifact
from polycolab.entities.enums import ArtifactState


class SqlArtifactStore:
    def __init__(self, session: Session) -> None:
        self._session = session

    @persistence_boundary
    def expired_for_update(
        self,
        *,
        states: tuple[ArtifactState, ...],
        before: datetime,
        limit: int,
        after: UUID | None,
    ) -> list[StoredArtifact]:
        query = select(SqlArtifact).where(
            SqlArtifact.state.in_(states),
            SqlArtifact.expires_at <= before,
        )
        if after is not None:
            query = query.where(SqlArtifact.id > after)
        return [
            artifact(row)
            for row in self._session.scalars(
                query.order_by(SqlArtifact.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ]

    @persistence_boundary
    def get_for_update(self, artifact_id: UUID) -> StoredArtifact | None:
        row = self._session.scalar(
            select(SqlArtifact)
            .where(SqlArtifact.id == artifact_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return artifact(row) if row is not None else None

    @persistence_boundary
    def set_state(
        self,
        artifact_id: UUID,
        state: ArtifactState,
        *,
        deleted_at: datetime | None = None,
    ) -> None:
        # The caller already holds this row's lock in the same transaction.
        statement = update(SqlArtifact).where(SqlArtifact.id == artifact_id).values(state=state)
        if deleted_at is not None:
            statement = statement.values(deleted_at=deleted_at)
        self._session.execute(statement)

"""Project-owned artifact lifecycle; database phases never perform storage I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.access.authorization import ProjectNotFound
from polycolab.artifacts.contracts import (
    ArtifactUploadDeclaration,
)
from polycolab.artifacts.storage import new_staging_key
from polycolab.db.converters.artifacts import artifact as _snapshot
from polycolab.db.models import (
    SqlAgentRun,
    SqlArtifact,
    SqlHostedRunArtifact,
)
from polycolab.entities.artifacts import StoredArtifact as StoredArtifact
from polycolab.entities.enums import ArtifactState
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings
from polycolab.projects.access import project_access
from polycolab.projects.service import DomainConflict


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _artifact(
    session: Session, artifact_id: UUID, project_id: UUID, *, lock: bool = False
) -> SqlArtifact:
    query = (
        select(SqlArtifact)
        .where(SqlArtifact.id == artifact_id, SqlArtifact.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    row = session.scalar(query)
    if row is None:
        raise ProjectNotFound
    return row


def reserve(
    session: Session,
    *,
    project_id: UUID,
    user_id: UUID,
    declaration: ArtifactUploadDeclaration,
    settings: Settings,
    commit: bool = True,
) -> StoredArtifact:
    """Commit identity first so ambiguous PUTs are durably discoverable by GC."""
    if declaration.byte_length > settings.artifact_max_bytes:
        raise DomainConflict("artifact exceeds configured byte limit")
    try:
        project_access(session, project_id, user_id, write=True)
        row = SqlArtifact(
            project_id=project_id,
            created_by_user_id=user_id,
            sha256=declaration.sha256,
            byte_length=declaration.byte_length,
            media_type=declaration.media_type,
            storage_key=new_staging_key(),
            state=ArtifactState.STAGING,
            expires_at=utc_now() + timedelta(seconds=settings.artifact_staging_ttl_seconds),
        )
        session.add(row)
        session.flush()
        result = _snapshot(row)
        if commit:
            session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def verified(
    session: Session, *, project_id: UUID, user_id: UUID, artifact_id: UUID
) -> StoredArtifact:
    """Called only after the service adapter has verified uploaded/read-back bytes."""
    try:
        project_access(session, project_id, user_id, write=True)
        row = _artifact(session, artifact_id, project_id, lock=True)
        if session.get(SqlHostedRunArtifact, artifact_id) is not None:
            raise DomainConflict("hosted artifacts are committed by run completion")
        if row.created_by_user_id != user_id:
            raise ProjectNotFound
        if row.state != ArtifactState.STAGING or _utc(row.expires_at) <= utc_now():
            raise DomainConflict("artifact staging expired or was collected")
        if row.verified_at is None:
            row.verified_at = utc_now()
        row.state = ArtifactState.COMMITTED
        row.committed_at = utc_now()
        result = _snapshot(row)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def read(
    session: Session,
    *,
    project_id: UUID,
    user_id: UUID,
    artifact_id: UUID,
    include_staging: bool = False,
) -> StoredArtifact:
    project_access(session, project_id, user_id, write=False)
    row = _artifact(session, artifact_id, project_id)
    binding = session.get(SqlHostedRunArtifact, artifact_id)
    if binding is not None:
        run = session.get(SqlAgentRun, binding.run_id)
        if run is None or run.requested_by_user_id != user_id or run.status != "COMPLETED":
            raise ProjectNotFound
    if row.state != ArtifactState.COMMITTED and not (
        include_staging
        and row.state == ArtifactState.STAGING
        and row.created_by_user_id == user_id
        and _utc(row.expires_at) > utc_now()
    ):
        raise ProjectNotFound
    return _snapshot(row)

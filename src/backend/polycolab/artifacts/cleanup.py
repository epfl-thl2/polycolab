"""Artifact cleanup policy and transaction phases, independent of SQL."""

from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID

from polycolab.artifacts.storage import ArtifactStorage
from polycolab.entities.artifacts import ArtifactStorageError, StoredArtifact
from polycolab.entities.enums import ArtifactState
from polycolab.entities.time import utc_now
from polycolab.projects.service import DomainConflict
from polycolab.transaction import Transaction, TransactionFactory


def claim_expired(
    transaction: Transaction,
    *,
    grace_seconds: int,
    limit: int = 100,
    after: UUID | None = None,
) -> list[StoredArtifact]:
    """Fence expired staging bytes and retain tombstones for ambiguous PUT retries."""
    if not 1 <= limit <= 100 or grace_seconds < 0:
        raise ValueError("invalid artifact sweep bounds")
    try:
        rows = transaction.artifacts.expired_for_update(
            states=(ArtifactState.STAGING, ArtifactState.DELETING, ArtifactState.DELETED),
            before=utc_now() - timedelta(seconds=grace_seconds),
            limit=limit,
            after=after,
        )
        result = []
        for row in rows:
            if row.state == ArtifactState.STAGING:
                transaction.artifacts.set_state(row.id, ArtifactState.DELETING)
                row = replace(row, state=ArtifactState.DELETING)
            result.append(row)
        transaction.commit()
        return result
    except Exception:
        transaction.rollback()
        raise


def deleted(transaction: Transaction, *, artifact_id: UUID) -> None:
    """Record successful storage deletion; retain its sweepable tombstone."""
    try:
        row = transaction.artifacts.get_for_update(artifact_id)
        if row is None or row.state not in {ArtifactState.DELETING, ArtifactState.DELETED}:
            raise DomainConflict("artifact was not claimed by garbage collection")
        if row.state == ArtifactState.DELETING:
            transaction.artifacts.set_state(row.id, ArtifactState.DELETED, deleted_at=utc_now())
        transaction.commit()
    except Exception:
        transaction.rollback()
        raise


@dataclass(frozen=True)
class SweepPage:
    next_cursor: UUID | None
    deleted_count: int
    failure_count: int


def sweep_page(
    factory: TransactionFactory,
    storage: ArtifactStorage,
    *,
    grace_seconds: int,
    after: UUID | None = None,
    limit: int = 100,
) -> SweepPage:
    with factory() as transaction:
        rows = claim_expired(transaction, grace_seconds=grace_seconds, limit=limit, after=after)
    failures = 0
    for row in rows:
        try:
            storage.delete(row.storage_key)
        except ArtifactStorageError:
            failures += 1
            continue
        with factory() as transaction:
            deleted(transaction, artifact_id=row.id)
    return SweepPage(rows[-1].id if len(rows) == limit else None, len(rows) - failures, failures)

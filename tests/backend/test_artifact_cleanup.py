"""Cleanup policy tests without SQL or a byte-storage service."""

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from polycolab.artifacts.cleanup import sweep_page
from polycolab.artifacts.storage import ArtifactStorage
from polycolab.entities.artifacts import ArtifactIntegrity, StoredArtifact
from polycolab.entities.enums import ArtifactState
from polycolab.entities.time import utc_now
from polycolab.transaction import PersistenceError


def staged_artifact() -> StoredArtifact:
    return StoredArtifact(
        id=uuid4(),
        integrity=ArtifactIntegrity("a" * 64, 3),
        media_type="text/plain",
        state=ArtifactState.STAGING,
        expires_at=utc_now() - timedelta(hours=2),
        storage_key="artifacts/test",
    )


def test_cleanup_closes_claim_before_storage_and_records_deletion_separately() -> None:
    row = staged_artifact()
    claim, record = MagicMock(), MagicMock()
    claim.__enter__.return_value = claim
    record.__enter__.return_value = record
    claim.artifacts.expired_for_update.return_value = [row]
    from dataclasses import replace

    record.artifacts.get_for_update.return_value = replace(row, state=ArtifactState.DELETING)
    factory = MagicMock(side_effect=[claim, record])
    storage = MagicMock(spec=ArtifactStorage)
    events: list[str] = []
    claim.commit.side_effect = lambda: events.append("claim committed")
    claim.__exit__.side_effect = lambda *args: events.append("claim closed")
    storage.delete.side_effect = lambda key: events.append("bytes deleted")
    record.commit.side_effect = lambda: events.append("deletion recorded")
    result = sweep_page(factory, storage, grace_seconds=0, limit=1)
    assert events == ["claim committed", "claim closed", "bytes deleted", "deletion recorded"]
    assert result.next_cursor == row.id
    assert result.deleted_count == 1
    assert result.failure_count == 0
    claim.artifacts.set_state.assert_called_once_with(row.id, ArtifactState.DELETING)
    assert record.artifacts.set_state.call_args.args == (row.id, ArtifactState.DELETED)
    assert record.artifacts.set_state.call_args.kwargs["deleted_at"] is not None


def test_failed_claim_rolls_back_without_deleting_bytes() -> None:
    claim = MagicMock()
    claim.__enter__.return_value = claim
    claim.artifacts.expired_for_update.return_value = [staged_artifact()]
    claim.commit.side_effect = PersistenceError
    storage = MagicMock(spec=ArtifactStorage)
    with pytest.raises(PersistenceError):
        sweep_page(MagicMock(return_value=claim), storage, grace_seconds=0)
    claim.rollback.assert_called_once()
    storage.delete.assert_not_called()

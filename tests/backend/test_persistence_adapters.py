"""Application store errors and detached artifact conversion."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from polycolab.db.converters.artifacts import artifact
from polycolab.db.models import SqlArtifact
from polycolab.entities.enums import ArtifactState


@pytest.mark.parametrize(
    "expiry",
    [
        datetime(2026, 9, 17, 12),
        datetime(2026, 9, 17, 12, tzinfo=UTC),
        datetime(2026, 9, 17, 14, tzinfo=timezone(timedelta(hours=2))),
    ],
)
def test_artifact_converter_normalizes_expiry_without_session(expiry: datetime) -> None:
    row = SqlArtifact(
        id=uuid4(),
        sha256="a" * 64,
        byte_length=3,
        media_type="text/plain",
        state=ArtifactState.STAGING,
        expires_at=expiry,
        storage_key="internal-key",
    )
    snapshot = artifact(row)
    assert snapshot.expires_at == datetime(2026, 9, 17, 12, tzinfo=UTC)
    assert snapshot.expires_at.tzinfo is UTC
    assert snapshot.integrity.sha256 == "a" * 64
    assert snapshot.integrity.byte_length == 3
    assert snapshot.storage_key == "internal-key"
    assert "internal-key" not in repr(snapshot)
    assert not hasattr(snapshot, "_sa_instance_state")

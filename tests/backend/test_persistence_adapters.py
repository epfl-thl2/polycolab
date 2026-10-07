"""Application store errors and detached artifact conversion."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from polycolab.db.base import Base
from polycolab.db.converters.artifacts import artifact
from polycolab.db.models import SqlArtifact, SqlUser
from polycolab.db.session import make_engine
from polycolab.db.stores.research import SqlResearchReadStore
from polycolab.entities.enums import ArtifactState
from polycolab.platform.config import Settings
from polycolab.transaction import PersistenceConflict, PersistenceError


def reader(store: SqlResearchReadStore, operation: str) -> Callable[[Sequence[UUID]], object]:
    return {
        "objects": store.objects,
        "versions": store.versions,
        "relationships": store.relationships,
    }[operation]


@pytest.mark.parametrize("operation", ["objects", "versions", "relationships"])
@pytest.mark.parametrize("failure", ["query", "constraint"])
def test_research_reads_translate_sql_errors(operation: str, failure: str) -> None:
    engine = make_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
    try:
        if failure == "constraint":
            Base.metadata.create_all(engine)
        with Session(engine) as session:
            store = SqlResearchReadStore(session)
            if failure == "constraint":
                # Autoflush discovers an invalid pending write before the read.
                session.add(SqlUser())
            error_type = PersistenceConflict if failure == "constraint" else PersistenceError
            with pytest.raises(error_type) as caught:
                reader(store, operation)([uuid4()])
            cause_type = IntegrityError if failure == "constraint" else OperationalError
            assert isinstance(caught.value.__cause__, cause_type)
            assert str(caught.value) == ""
            session.rollback()
            # Caller retains transaction ownership and can reuse the session.
            if failure == "constraint":
                assert reader(store, operation)([uuid4()]) == {}
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["objects", "versions", "relationships"])
def test_invalid_research_batch_remains_a_validation_error(operation: str) -> None:
    with Session() as session:
        store = SqlResearchReadStore(session)
        with pytest.raises(ValueError, match="exceeds 128"):
            reader(store, operation)([uuid4() for _ in range(129)])
        assert reader(store, operation)([]) == {}


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

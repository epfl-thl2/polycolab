"""Core owns background startup, independent jobs, and graceful shutdown."""

from pathlib import Path
from threading import Event, current_thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from polycolab.app import maintenance
from polycolab.app.application import create_app
from polycolab.db.base import Base
from polycolab.db.models import SqlCommunityDeliveryCursor, SqlOutboxEvent
from polycolab.platform.config import Settings
from polycolab.platform.outbox import canonical_digest


def test_core_starts_jobs_and_finishes_them_before_disposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'core.db'}",
            artifact_local_directory=tmp_path / "artifacts",
        ),
        background_jobs=True,
    )
    started = {
        name: Event() for name in ("notifications", "execution-recovery", "artifact-cleanup")
    }
    finished: list[str] = []
    disposal: list[set[str]] = []

    def job(*args: object, **kwargs: object) -> None:
        stopped = args[-1]
        assert isinstance(stopped, Event)
        name = current_thread().name
        started[name].set()
        assert stopped.wait(10)
        # Shutdown must leave the pool available until each job has finished.
        with app.state.session_factory() as session:
            assert session.scalar(text("SELECT 1")) == 1
        finished.append(name)

    for name in ("consume_notifications", "recover_execution", "collect_artifacts"):
        monkeypatch.setattr(maintenance, name, job)
    original_dispose = app.state.engine.dispose

    def dispose() -> None:
        disposal.append(set(finished))
        original_dispose()

    monkeypatch.setattr(app.state.engine, "dispose", dispose)
    with TestClient(app) as client:
        for event in started.values():
            assert event.wait(5)
        assert client.get("/health/live").status_code == 200
        assert not finished
    assert disposal == [set(started)]


def test_asgi_entrypoint_runs_recovery_without_execution_or_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from polycolab.main import app

    settings = Settings(database_url="sqlite:///:memory:")
    assert not settings.feature_agent_execution_enabled
    assert not settings.artifact_storage_configured
    monkeypatch.setattr(app.state, "settings", settings)
    started = {name: Event() for name in ("notifications", "execution-recovery")}

    def job(*args: object) -> None:
        stopped = args[-1]
        assert isinstance(stopped, Event)
        started[current_thread().name].set()
        assert stopped.wait(10)

    def unexpected_storage(*args: object) -> None:
        pytest.fail("Unconfigured artifact storage must not be opened")

    monkeypatch.setattr(maintenance, "consume_notifications", job)
    monkeypatch.setattr(maintenance, "recover_execution", job)
    monkeypatch.setattr(maintenance, "configured_storage", unexpected_storage)
    with TestClient(app):
        for event in started.values():
            assert event.wait(5)


def test_core_processes_durable_outbox_without_a_separate_consumer(tmp_path: Path) -> None:
    app = create_app(
        Settings(database_url=f"sqlite:///{tmp_path / 'outbox.db'}"), background_jobs=True
    )
    Base.metadata.create_all(app.state.engine)
    event_id = uuid4()
    with app.state.session_factory() as session:
        # Private research events are consumed without producing public notifications.
        session.add(
            SqlOutboxEvent(
                id=event_id,
                event_type="research.created",
                aggregate_type="OBJECT_REVISION",
                aggregate_id=uuid4(),
                payload={},
                payload_digest=canonical_digest({}),
            )
        )
        session.commit()
    with TestClient(app) as client:
        deadline = monotonic() + 5
        while True:
            with app.state.session_factory() as session:
                cursor = session.get(SqlCommunityDeliveryCursor, event_id)
                if cursor is not None and cursor.done:
                    break
            assert monotonic() < deadline, "Core did not consume the durable outbox event"
            sleep(0.01)
        assert client.get("/health/ready").status_code == 200

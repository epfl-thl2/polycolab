"""Core owns background startup, independent jobs, and graceful shutdown."""

from pathlib import Path
from threading import Event, current_thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from polycolab.app import maintenance
from polycolab.app.application import create_app
from polycolab.platform.config import Settings


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
        name: Event() for name in ("execution-recovery", "artifact-cleanup", "document-builds")
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

    for name in ("recover_execution", "collect_artifacts", "collect_document_builds"):
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
    started = {name: Event() for name in ("execution-recovery",)}

    def job(*args: object) -> None:
        stopped = args[-1]
        assert isinstance(stopped, Event)
        started[current_thread().name].set()
        assert stopped.wait(10)

    def unexpected_storage(*args: object) -> None:
        pytest.fail("Unconfigured artifact storage must not be opened")

    monkeypatch.setattr(maintenance, "recover_execution", job)
    monkeypatch.setattr(maintenance, "configured_storage", unexpected_storage)
    with TestClient(app):
        for event in started.values():
            assert event.wait(5)

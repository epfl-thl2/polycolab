"""Local community exporter checks; no PostgreSQL, container or agent runtime."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.accounts.builtin import create_account, create_session, revoke_session
from polycolab.catalogue import community_consumer, community_metrics
from polycolab.catalogue.community_metrics import create_metrics_app, private_metrics_socket
from polycolab.db.base import Base
from polycolab.db.session import make_session_factory
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.operations.pool_telemetry import PoolMeter
from polycolab.operations.telemetry import PoolRole
from polycolab.platform.config import Settings


@pytest.fixture
def metered(tmp_path: Path) -> Iterator[tuple[Settings, Engine, PoolMeter]]:
    settings = Settings(
        database_url="postgresql+psycopg://unused.example/polycolab",
        database_pool_size=2,
        database_max_overflow=0,
        operator_diagnostics_enabled=True,
        operator_diagnostics_subjects=["operator"],
    )
    meter = PoolMeter(settings, PoolRole.COMMUNITY)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'community.db'}",
        poolclass=meter.pool_class,
        pool_size=2,
        max_overflow=0,
        connect_args={"check_same_thread": False},
    )
    try:
        yield settings, engine, meter
    finally:
        engine.dispose()


def _verifier() -> MappingIdentityVerifier:
    return MappingIdentityVerifier(
        {
            "operator": Principal("test-issuer", "operator"),
            "outsider": Principal("test-issuer", "outsider"),
        }
    )


def test_metrics_report_only_current_community_pool(
    metered: tuple[Settings, Engine, PoolMeter],
) -> None:
    settings, engine, meter = metered
    app = create_metrics_app(settings, engine, meter, identity_verifier=_verifier())
    with TestClient(app) as client, engine.connect():
        response = client.get("/internal/v1/metrics", headers={"Authorization": "Bearer operator"})
    assert response.status_code == 200
    assert 'polycolab_database_pool_checked_out{role="community"} 1.000000' in response.text
    assert 'role="api"' not in response.text
    assert "polycolab_outbox" not in response.text
    assert "unused.example" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    ("enabled", "token", "status"),
    [(False, "operator", 404), (True, "", 401), (True, "outsider", 403)],
)
def test_denials_precede_pool_rendering(
    metered: tuple[Settings, Engine, PoolMeter],
    monkeypatch: pytest.MonkeyPatch,
    enabled: bool,
    token: str,
    status: int,
) -> None:
    settings, engine, meter = metered
    settings.operator_diagnostics_enabled = enabled

    def fail(*args: object) -> str:
        raise AssertionError("denied requests must not render metrics")

    monkeypatch.setattr(meter, "render", fail)
    app = create_metrics_app(settings, engine, meter, identity_verifier=_verifier())
    with TestClient(app) as client:
        response = client.get("/internal/v1/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure", ["identity", "meter"])
def test_runtime_failures_are_sanitized(
    metered: tuple[Settings, Engine, PoolMeter], monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    settings, engine, meter = metered
    verifier = _verifier()

    def fail(*args: object) -> Any:
        raise RuntimeError("private-database-and-credential-details")

    monkeypatch.setattr(
        verifier if failure == "identity" else meter,
        "verify" if failure == "identity" else "render",
        fail,
    )
    with TestClient(
        create_metrics_app(settings, engine, meter, identity_verifier=verifier)
    ) as client:
        response = client.get("/internal/v1/metrics", headers={"Authorization": "Bearer operator"})
    assert response.status_code == 503
    assert response.text == "Diagnostics unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_no_application_routes_or_request_bodies(
    metered: tuple[Settings, Engine, PoolMeter],
) -> None:
    settings, engine, meter = metered
    with TestClient(
        create_metrics_app(settings, engine, meter, identity_verifier=_verifier())
    ) as client:
        for path in [
            "/auth/setup",
            "/auth/login",
            "/docs",
            "/openapi.json",
            "/api/v1/workspaces",
            "/",
        ]:
            response = client.get(path)
            assert response.status_code == 404
            assert response.headers["cache-control"] == "no-store"
        assert client.post("/internal/v1/metrics").status_code == 405
        assert client.request("GET", "/internal/v1/metrics", content="private").status_code == 400


@pytest.fixture
def socket_path() -> Iterator[Path]:
    # Keep paths below AF_UNIX's platform length limit, unlike long pytest dirs.
    with TemporaryDirectory(prefix="pc-metrics-") as directory:
        yield Path(directory).resolve() / "metrics.sock"


def test_socket_is_private_and_cleaned(socket_path: Path) -> None:
    with private_metrics_socket(socket_path) as listener:
        assert socket_path.is_socket()
        assert socket_path.stat().st_mode & 0o777 == 0o600
        assert listener.getsockname() == str(socket_path)
    assert not socket_path.exists()


def test_real_consumer_sigterm_cleans_socket(
    metered: tuple[Settings, Engine, PoolMeter], socket_path: Path
) -> None:
    _, engine, _ = metered
    Base.metadata.create_all(engine)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "polycolab.catalogue.community_consumer",
            "--metrics-uds",
            str(socket_path),
        ],
        cwd=Path(__file__).resolve().parents[2] / "backend",
        env={
            "PATH": os.environ["PATH"],
            "APP_ENV": "local",
            "AUTH_MODE": "local",
            "DATABASE_URL": str(engine.url),
            "OPERATOR_DIAGNOSTICS_ENABLED": "true",
            "OPERATOR_DIAGNOSTICS_SUBJECTS": '["operator"]',
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = False
        deadline = monotonic() + 5
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path)),
            base_url="http://community",
            timeout=0.2,
        ) as client:
            while monotonic() < deadline and process.poll() is None:
                try:
                    ready = client.get("/internal/v1/metrics").status_code == 401
                except httpx.TransportError:
                    pass
                if ready:
                    break
                Event().wait(0.02)
        assert ready, "community subprocess failed to become ready"
        process.terminate()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert not socket_path.exists()
        assert "community_consumer_service_failed" not in stdout + stderr
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.parametrize("kind", ["file", "symlink", "socket"])
def test_existing_paths_are_never_removed(socket_path: Path, kind: str) -> None:
    import socket

    existing = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        if kind == "socket":
            existing.bind(str(socket_path))
        elif kind == "file":
            socket_path.write_text("preserve")
        else:
            socket_path.symlink_to(socket_path.parent / "absent")
        identity = socket_path.lstat()
        with pytest.raises((OSError, ValueError)), private_metrics_socket(socket_path):
            pytest.fail("existing target accepted")
        assert socket_path.lstat().st_ino == identity.st_ino
    finally:
        existing.close()


def test_socket_cleanup_preserves_replacement(socket_path: Path) -> None:
    with private_metrics_socket(socket_path):
        socket_path.unlink()
        socket_path.write_text("replacement")
    assert socket_path.read_text() == "replacement"


def test_socket_rejects_shared_directory(socket_path: Path) -> None:
    socket_path.parent.chmod(0o755)
    with pytest.raises(ValueError, match="mode-700"), private_metrics_socket(socket_path):
        pytest.fail("shared directory accepted")
    assert not socket_path.exists()


def test_disabled_diagnostics_opens_no_engine_or_listener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(community_consumer, "get_settings", lambda: Settings())

    def fail(*args: object, **kwargs: object) -> Any:
        raise AssertionError("disabled consumer must not start services")

    monkeypatch.setattr(community_consumer, "make_engine", fail)
    monkeypatch.setattr(community_consumer, "run_metrics_consumer", fail)
    with pytest.raises(SystemExit) as rejected:
        community_consumer.main(["--metrics-uds", "/private/unused.sock"])
    assert rejected.value.code == 2


def test_default_consumer_stays_listener_free_and_disposes_engine(
    metered: tuple[Settings, Engine, PoolMeter], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, engine, _ = metered
    consumed: list[bool] = []
    disposed: list[bool] = []
    monkeypatch.setattr(community_consumer, "get_settings", lambda: settings)
    monkeypatch.setattr(community_consumer, "make_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr("polycolab.catalogue.community_consumer.signal.signal", lambda *args: None)
    monkeypatch.setattr(community_consumer, "consume", lambda *args: consumed.append(True))
    monkeypatch.setattr(engine, "dispose", lambda: disposed.append(True))

    def fail(*args: object) -> None:
        raise AssertionError("default consumer must not start a listener")

    monkeypatch.setattr(community_consumer, "run_metrics_consumer", fail)
    assert community_consumer.main([]) == 0
    assert consumed == [True] and disposed == [True]


def test_export_start_failure_disposes_engine_without_private_diagnostics(
    metered: tuple[Settings, Engine, PoolMeter],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings, engine, _ = metered
    disposed: list[bool] = []
    monkeypatch.setattr(community_consumer, "get_settings", lambda: settings)
    monkeypatch.setattr(community_consumer, "make_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(engine, "dispose", lambda: disposed.append(True))

    def fail(*args: object) -> None:
        raise RuntimeError("private-startup-details")

    monkeypatch.setattr(community_consumer, "run_metrics_consumer", fail)
    assert community_consumer.main(["--metrics-uds", "/private/unused.sock"]) == 1
    assert disposed == [True]
    assert "community_consumer_service_failed" in caplog.text
    assert "private-startup-details" not in caplog.text


def test_real_unix_export_reuses_local_auth_and_stops_consumer(
    metered: tuple[Settings, Engine, PoolMeter], socket_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, engine, meter = metered
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        account = create_account(
            SqlAlchemyTransaction(session),
            username="operator",
            password="synthetic strong password",
            display_name=None,
        )
        token = create_session(
            SqlAlchemyTransaction(session), account_id=account.id, ttl_seconds=60
        )
        settings.operator_diagnostics_subjects = [str(account.id)]
    ready, consumer_started, consumer_finished, stopped = Event(), Event(), Event(), Event()
    servers: list[uvicorn.Server] = []
    failures: list[BaseException] = []

    class ObservedServer(uvicorn.Server):
        def __init__(self, config: uvicorn.Config) -> None:
            super().__init__(config)
            servers.append(self)

        async def startup(self, sockets: Any = None) -> None:
            await super().startup(sockets=sockets)
            ready.set()

    monkeypatch.setattr(uvicorn, "Server", ObservedServer)

    def consume() -> None:
        with engine.connect():
            consumer_started.set()
            stopped.wait(10)
        consumer_finished.set()

    def serve() -> None:
        try:
            community_metrics.run_metrics_consumer(
                settings, engine, meter, socket_path, consume, stopped
            )
        except BaseException as exc:
            failures.append(exc)
            ready.set()

    thread = Thread(target=serve)
    thread.start()
    try:
        assert ready.wait(5) and not failures
        assert consumer_started.wait(1)
        with httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path)),
            base_url="http://community",
            timeout=2,
        ) as client:
            assert client.get("/internal/v1/metrics").status_code == 401
            client.cookies.set(settings.local_auth_cookie_name, token)
            response = client.get("/internal/v1/metrics")
            assert response.status_code == 200
            assert 'checked_out{role="community"} 1.000000' in response.text
            assert token not in response.text
            with factory() as session:
                revoke_session(SqlAlchemyTransaction(session), token)
            assert client.get("/internal/v1/metrics").status_code == 401
    finally:
        for server in servers:
            server.should_exit = True
        thread.join(5)
        if thread.is_alive():
            stopped.set()
            thread.join(5)
            pytest.fail("server shutdown did not stop and join its consumer")
    assert not thread.is_alive()
    assert consumer_finished.is_set()
    assert not failures
    assert not socket_path.exists()

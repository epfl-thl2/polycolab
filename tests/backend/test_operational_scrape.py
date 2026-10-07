"""Protected scrape wiring with SQLite; PostgreSQL primitive coverage is separate."""

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Connection
from test_operational_telemetry import _event

from polycolab.entities.time import utc_now
from polycolab.operations import scrape as operational_scrape
from polycolab.operations.scrape import CommunityScrape
from polycolab.operations.telemetry import (
    CommunityOutboxSnapshot,
    publish_community_outbox_snapshot,
)


def test_authorized_scrape_reports_canonical_backlog_without_payloads(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.operator_diagnostics_enabled = True
    app.state.settings.operator_diagnostics_subjects = ["owner"]
    with app.state.session_factory() as session:
        session.add(_event(created_at=utc_now(), payload={"secret": "private-research-content"}))
        session.commit()
    response = client.get("/internal/v1/metrics", headers={"Authorization": "Bearer owner"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'polycolab_outbox_pending_events{consumer="community"} 1.000000' in response.text
    assert "private-research-content" not in response.text
    assert 'source="community_outbox"' in response.text
    again = client.get("/internal/v1/metrics", headers={"Authorization": "Bearer owner"})
    assert (
        'polycolab_operational_snapshot_total{outcome="success",source="community_outbox"} 2'
        in again.text
    )


@pytest.mark.parametrize(
    ("enabled", "identity", "status"),
    [(False, "owner", 404), (True, "outsider", 403), (True, "", 401)],
)
def test_denied_scrape_never_reads_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, enabled: bool, identity: str, status: int
) -> None:
    app = cast(FastAPI, client.app)
    app.state.settings.operator_diagnostics_enabled = enabled
    app.state.settings.operator_diagnostics_subjects = ["owner"]

    def fail() -> str:
        raise AssertionError("must authorize before telemetry read")

    monkeypatch.setattr(app.state.community_scrape, "render", fail)
    monkeypatch.setattr(app.state.pool_meter, "render", lambda *_: fail())
    response = client.get(
        "/internal/v1/metrics", headers={"Authorization": f"Bearer {identity}"} if identity else {}
    )
    assert response.status_code == status


def test_snapshot_failure_omits_stale_gauges_and_recovers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, client.app)
    scrape = app.state.community_scrape
    assert "polycolab_outbox_pending_events" in scrape.render()

    def fail(*args: Any) -> CommunityOutboxSnapshot:
        raise RuntimeError("private-database-details")

    with monkeypatch.context() as patch:
        patch.setattr(operational_scrape, "community_outbox_snapshot", fail)
        failed = scrape.render()
    assert "polycolab_outbox_pending_events" not in failed
    assert "polycolab_outbox_oldest_pending_age_seconds" not in failed
    assert 'outcome="error"' in failed and "private-database-details" not in failed
    assert "polycolab_outbox_pending_events" in scrape.render()


def test_snapshot_transaction_is_closed_before_publishing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = cast(FastAPI, client.app)
    active: set[int] = set()
    event.listen(app.state.engine, "begin", lambda connection: active.add(id(connection)))

    def ended(connection: Connection) -> None:
        active.discard(id(connection))

    event.listen(app.state.engine, "rollback", ended)
    event.listen(app.state.engine, "commit", ended)

    def checked(*args: Any) -> None:
        assert not active
        publish_community_outbox_snapshot(*args)

    monkeypatch.setattr(operational_scrape, "publish_community_outbox_snapshot", checked)
    app.state.community_scrape.render()
    fresh = CommunityScrape(app.state.session_factory)
    assert 'source="community_outbox"} 1' in fresh.render()

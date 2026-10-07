from __future__ import annotations

from fastapi.testclient import TestClient

import polycolab.app.application


def test_readiness_reports_database_unavailable(monkeypatch: object, client: TestClient) -> None:
    monkeypatch.setattr(polycolab.app.application, "database_is_ready", lambda _: False)  # type: ignore[attr-defined]

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}

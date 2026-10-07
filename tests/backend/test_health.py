from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_includes_request_id(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "polycolab-api"}
    assert response.headers["X-Request-ID"]


def test_request_id_is_preserved_when_valid(client: TestClient) -> None:
    request_id = "5704b9c3-3e91-4b3e-b96f-0044710da6a4"

    response = client.get("/health/live", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_not_found_uses_non_disclosing_error_envelope(client: TestClient) -> None:
    response = client.get("/not-a-route")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]

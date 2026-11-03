"""Retired direct-provider execution has no compatibility API."""

from uuid import uuid4

from fastapi.testclient import TestClient


def test_direct_inference_routes_are_retired(client: TestClient) -> None:
    headers = {"Authorization": "Bearer owner"}
    assert client.post("/api/v1/chat/conversations", headers=headers, json={}).status_code == 404
    assert client.get("/api/v1/chat/conversations", headers=headers).status_code == 404
    assert (
        client.post(
            f"/api/v1/chat/conversations/{uuid4()}/turns", headers=headers, json={}
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/chat/conversations/{uuid4()}/turns", headers=headers).status_code
        == 404
    )

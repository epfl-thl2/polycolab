from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient


def headers(token: str = "owner") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


def create_project(client: TestClient, *, visibility: str = "PRIVATE") -> str:
    response = client.post(
        "/api/v1/projects",
        headers=headers(),
        json={"name": "Project", "visibility": visibility},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["id"])


def current_user_id(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/users/me", headers=headers(token))
    assert response.status_code == 200
    return cast(str, response.json()["id"])


def add_member(client: TestClient, project_id: str, token: str, role: str) -> None:
    response = client.post(
        f"/api/v1/projects/{project_id}/members",
        headers=headers(),
        json={"user_id": current_user_id(client, token), "role": role},
    )
    assert response.status_code == 201, response.text

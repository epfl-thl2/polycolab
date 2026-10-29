"""Project artifact access, byte verification, and revocation at the HTTP boundary."""

from __future__ import annotations

import hashlib
from typing import Any, cast

import pytest
from artifact_support import MemoryS3
from fastapi.testclient import TestClient
from workspace_support import add_member, create_project, headers

from polycolab.artifacts.storage import GarageStorage


@pytest.fixture
def artifact_client(client: TestClient) -> TestClient:
    cast(Any, client.app).state.artifact_storage = GarageStorage(MemoryS3(), "private-test")
    return client


def upload(client: TestClient, project: str, data: bytes = b"abc", **kwargs: Any) -> Any:
    return client.post(
        f"/api/v1/projects/{project}/artifacts",
        content=data,
        headers=headers(),
        params={
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_length": len(data),
            **kwargs,
        },
    )


def test_verified_upload_commits_and_download_is_private(
    artifact_client: TestClient,
) -> None:
    project = create_project(artifact_client, visibility="PUBLIC")
    data = b"<script>untrusted()</script>"
    response = upload(artifact_client, project, data, media_type="text/html")
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "COMMITTED"
    assert "storage_key" not in response.text
    url = f"/api/v1/projects/{project}/artifacts/{response.json()['id']}/content"
    result = artifact_client.get(url, headers=headers())
    assert result.status_code == 200
    assert result.content == data
    assert result.headers["content-type"] == "application/octet-stream"
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["content-disposition"].startswith("attachment;")
    assert artifact_client.get(url).status_code == 401
    assert artifact_client.get(url, headers=headers("outsider")).status_code == 404


def test_project_membership_gates_artifacts_and_archived_writes(
    artifact_client: TestClient,
) -> None:
    client = artifact_client
    project = create_project(client)
    add_member(client, project, "reader", "READ_ONLY")
    artifact = upload(client, project).json()["id"]
    url = f"/api/v1/projects/{project}/artifacts/{artifact}/content"
    assert client.get(url, headers=headers("reader")).status_code == 200
    denied = client.post(
        f"/api/v1/projects/{project}/artifacts",
        headers=headers("reader"),
        params={"sha256": hashlib.sha256(b"abc").hexdigest(), "byte_length": 3},
        content=b"abc",
    )
    assert denied.status_code == 403
    assert (
        client.patch(
            f"/api/v1/projects/{project}", headers=headers(), json={"archived": True}
        ).status_code
        == 200
    )
    assert client.get(url, headers=headers()).status_code == 200
    assert upload(client, project).status_code == 403


def test_artifact_id_does_not_grant_cross_project_access(
    artifact_client: TestClient,
) -> None:
    first, second = create_project(artifact_client), create_project(artifact_client)
    artifact = upload(artifact_client, first).json()["id"]
    assert (
        artifact_client.get(
            f"/api/v1/projects/{second}/artifacts/{artifact}/content", headers=headers()
        ).status_code
        == 404
    )


def test_revocation_during_download_prevents_returning_bytes(
    artifact_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = artifact_client
    project = create_project(client)
    add_member(client, project, "reader", "READ_ONLY")
    artifact = upload(client, project).json()["id"]
    reader = client.get("/api/v1/users/me", headers=headers("reader")).json()["id"]
    store = cast(Any, client.app).state.artifact_storage
    original = store.client.get_object

    def retrieve(**kwargs: Any) -> Any:
        data = original(**kwargs)
        response = client.delete(f"/api/v1/projects/{project}/members/{reader}", headers=headers())
        assert response.status_code == 204
        return data

    monkeypatch.setattr(store.client, "get_object", retrieve)
    response = client.get(
        f"/api/v1/projects/{project}/artifacts/{artifact}/content",
        headers=headers("reader"),
    )
    assert response.status_code == 404
    assert b"abc" not in response.content


def test_invalid_bytes_never_commit(artifact_client: TestClient) -> None:
    project = create_project(artifact_client)
    response = upload(artifact_client, project, sha256="0" * 64)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "artifact_digest_mismatch"

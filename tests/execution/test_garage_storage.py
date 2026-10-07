"""Opt-in real Garage test; never uses an existing bucket or shared service."""

from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from polycolab.artifacts.storage import (
    ArtifactIntegrity,
    ArtifactStorageError,
    GarageStorage,
    garage_storage,
    new_staging_key,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("POLYCOLAB_TEST_GARAGE") != "1",
    reason="Set POLYCOLAB_TEST_GARAGE=1 to start an isolated disposable Docker service",
)


def docker(*args: str, environment: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=environment,
        check=False,
    )
    # Do not print Docker config, credentials, or server logs on failure.
    if result.returncode:
        raise RuntimeError(f"Garage test Docker {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


@dataclass(frozen=True)
class GarageService:
    project: str
    environment: dict[str, str] = field(repr=False)

    def compose(self, *args: str) -> str:
        profile = Path(__file__).resolve().parents[2] / "deploy/garage/compose.yaml"
        return docker(
            "compose",
            "--project-name",
            self.workspace,
            "--file",
            str(profile),
            *args,
            environment=self.environment,
        )

    def connect(self) -> GarageStorage:
        address = self.compose("port", "garage", "3900")
        assert address.startswith("127.0.0.1:") and "\n" not in address
        store = garage_storage(
            endpoint=f"http://{address}",
            bucket="artifact-test",
            region="garage",
            access_key=self.environment["GARAGE_DEFAULT_ACCESS_KEY"],
            secret_key=self.environment["GARAGE_DEFAULT_SECRET_KEY"],
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                store.client.head_bucket(Bucket="artifact-test")
                return store
            except Exception:
                if time.monotonic() >= deadline:
                    store.client.close()
                    raise RuntimeError("Isolated Garage did not become ready") from None
                time.sleep(0.2)


@pytest.fixture(scope="module")
def service() -> Iterator[GarageService]:
    environment = {
        **os.environ,
        "GARAGE_RPC_SECRET": secrets.token_hex(32),
        "GARAGE_DEFAULT_ACCESS_KEY": f"GK{secrets.token_hex(16)}",
        "GARAGE_DEFAULT_SECRET_KEY": secrets.token_hex(32),
        "GARAGE_DEFAULT_BUCKET": "artifact-test",
        "POLYCOLAB_GARAGE_PORT": "0",
        # Do not inherit a developer's Compose override/profile files.
        "COMPOSE_FILE": "",
        "COMPOSE_PROFILES": "",
        "COMPOSE_ENV_FILES": "",
        "COMPOSE_DISABLE_ENV_FILE": "1",
    }
    instance = GarageService(f"polycolab-platform-garage-{uuid4().hex}", environment)
    try:
        instance.compose("up", "--detach", "--wait", "--wait-timeout", "30")
        yield instance
    finally:
        # The name was generated here; only this fixture's disposable volumes
        # can be removed. Cleanup also covers partially failed initialization.
        instance.compose("down", "--volumes", "--timeout", "2")


@pytest.fixture
def storage(service: GarageService) -> Iterator[GarageStorage]:
    store = service.connect()
    try:
        yield store
    finally:
        store.client.close()


@pytest.mark.parametrize("data", [b"", b"<script>alert(1)</script>", b"x" * (1024 * 1024)])
def test_real_garage_roundtrip_and_delete(storage: GarageStorage, data: bytes) -> None:
    expected = ArtifactIntegrity(hashlib.sha256(data).hexdigest(), len(data))
    key = new_staging_key()
    storage.put_verified(key, BytesIO(data), expected)
    assert storage.get_verified(key, expected) == data
    storage.delete(key)
    storage.delete(key)  # A retry of an ambiguous deletion must succeed.
    with pytest.raises(ArtifactStorageError, match="artifact_storage_unavailable"):
        storage.get_verified(key, expected)


def test_real_garage_rejects_corrupted_bytes(storage: GarageStorage) -> None:
    key = new_staging_key()
    expected = ArtifactIntegrity(hashlib.sha256(b"good").hexdigest(), 4)
    storage.put_verified(key, BytesIO(b"good"), expected)
    # Deliberate service-side corruption proves the read boundary checks bytes.
    storage.client.put_object(Bucket=storage.bucket, Key=key, Body=b"evil")
    try:
        with pytest.raises(ArtifactStorageError, match="artifact_digest_mismatch"):
            storage.get_verified(key, expected)
    finally:
        storage.delete(key)


def test_profile_retains_bytes_after_container_replacement(service: GarageService) -> None:
    data = b"canonical bytes survive container replacement"
    expected = ArtifactIntegrity(hashlib.sha256(data).hexdigest(), len(data))
    key = new_staging_key()
    store = service.connect()
    try:
        store.put_verified(key, BytesIO(data), expected)
    finally:
        store.client.close()
    original_container = service.compose("ps", "--quiet", "garage")
    assert original_container
    service.compose("up", "--detach", "--force-recreate", "--wait", "--wait-timeout", "30")
    assert service.compose("ps", "--quiet", "garage") != original_container
    store = service.connect()
    try:
        assert store.get_verified(key, expected) == data
        store.delete(key)
    finally:
        store.client.close()


def test_authenticated_artifact_api_uses_real_garage(storage: GarageStorage) -> None:
    from fastapi.testclient import TestClient

    from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
    from polycolab.app.application import create_app
    from polycolab.artifacts.routes.private import router
    from polycolab.db.base import Base
    from polycolab.platform.config import Settings

    app = create_app(
        Settings(
            database_url="sqlite+pysqlite:///:memory:",
            web_dist_dir="/missing-artifact-test-web",
        ),
        MappingIdentityVerifier(
            {"owner": Principal("test", "owner", "owner@example.test", "Owner")}
        ),
    )
    app.include_router(router)
    app.state.artifact_storage = storage
    Base.metadata.create_all(app.state.engine)
    try:
        with TestClient(app) as client:
            auth = {"Authorization": "Bearer owner"}
            project = client.post("/api/v1/workspaces", headers=auth, json={"name": "Artifacts"})
            assert project.status_code == 201, project.text
            project_id = project.json()["id"]
            target = client.post(
                f"/api/v1/workspaces/{project_id}/objects",
                headers=auth,
                json={"kind": "CLAIM", "title": "Claim", "content_md": "Claim"},
            )
            assert target.status_code == 201, target.text
            data = b"<html><script>not executable</script></html>"
            response = client.post(
                f"/api/v1/workspaces/{project_id}/artifacts",
                headers=auth,
                content=data,
                params={
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "byte_length": len(data),
                    "media_type": "text/html",
                },
            )
            assert response.status_code == 201, response.text
            artifact = response.json()["id"]
            base = f"/api/v1/workspaces/{project_id}/artifacts/{artifact}"
            assert client.get(f"{base}/content", headers=auth).status_code == 404
            response = client.post(
                f"{base}/attachments",
                headers=auth,
                json={"revision_id": target.json()["current_revision_id"], "role": "EVIDENCE"},
            )
            assert response.status_code == 200, response.text
            result = client.get(f"{base}/content", headers=auth)
            assert result.status_code == 200 and result.content == data
            assert result.headers["content-type"] == "application/octet-stream"
            assert result.headers["cache-control"] == "private, no-store"
            assert result.headers["x-content-type-options"] == "nosniff"
            assert client.get(f"{base}/content").status_code == 401
    finally:
        app.state.engine.dispose()

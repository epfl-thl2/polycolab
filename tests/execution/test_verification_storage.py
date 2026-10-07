"""Opt-in real Garage/controller HTTP flow; no submitted code executes."""

import hashlib
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_garage_storage import service as service
from test_garage_storage import storage as storage

from polycolab.accounts.authentication import MappingIdentityVerifier, Principal
from polycolab.app.application import create_app
from polycolab.artifacts.storage import GarageStorage
from polycolab.db.base import Base
from polycolab.db.models import SqlVerificationEnvironment
from polycolab.entities.enums import VerificationLanguage
from polycolab.platform.config import Settings
from polycolab.verification.contracts import ResourceLimits

pytestmark = pytest.mark.skipif(
    os.environ.get("POLYCOLAB_TEST_GARAGE") != "1", reason="requires disposable Garage"
)


def test_controller_output_commits_real_verified_bytes(storage: GarageStorage) -> None:
    app = create_app(
        Settings(database_url="sqlite+pysqlite:///:memory:", web_dist_dir="/missing-job-test"),
        MappingIdentityVerifier(
            {"owner": Principal("test", "owner", "owner@example.test", "Owner")}
        ),
    )
    app.state.artifact_storage = storage
    app.state.settings.feature_catalogue_enabled = True
    app.state.settings.feature_verification_submission_enabled = True
    app.state.settings.feature_verification_execution_enabled = True
    app.state.settings.verification_controller_token = SecretStr("test-controller-only")
    Base.metadata.create_all(app.state.engine)
    limits = ResourceLimits(
        cpu_count=1,
        cpu_seconds=10,
        wall_seconds=60,
        memory_bytes=16 * 1024 * 1024,
        process_count=4,
        disk_bytes=1024 * 1024,
        output_bytes=1024,
        log_bytes=1024,
        output_files=4,
    )
    try:
        with app.state.session_factory() as session:
            env = SqlVerificationEnvironment(
                language=VerificationLanguage.PYTHON,
                image_digest=uuid4().hex * 2,
                toolchain_version="test-only",
                dependency_lock_digest="a" * 64,
                build_digest="b" * 64,
                platform_identity="test-only",
                available=True,
                **{f"max_{key}": value for key, value in limits.model_dump().items()},
            )
            session.add(env)
            session.commit()
            environment_id = str(env.id)
        with TestClient(app) as client:
            human = {"Authorization": "Bearer owner"}
            private = {"Authorization": "Bearer test-controller-only"}
            project = client.post(
                "/api/v1/workspaces", headers=human, json={"name": "Verification"}
            ).json()["id"]
            created = client.post(
                "/api/v1/objects",
                headers=human,
                json={
                    "destination": {"kind": "workspace", "workspace_id": project},
                    "snapshot": {
                        "kind": "COMPUTATION",
                        "content": {
                            "title": "Pinned source",
                            "content_md": "print(1)",
                            "assumptions_md": "Storage test only",
                            "reported_outcome": None,
                            "explanation_md": None,
                        },
                        "structural_relationships": [],
                    },
                },
            )
            assert created.status_code == 201, created.text
            revision = next(
                item["entity_id"]
                for item in created.json()["outputs"]
                if item["entity_type"] == "OBJECT_VERSION"
            )
            response = client.post(
                f"/api/v1/workspaces/{project}/verification-jobs",
                headers=human,
                json={
                    "retry_key": "garage",
                    "submission": {
                        "workspace_id": project,
                        "work_target_object_version_id": revision,
                        "environment_id": environment_id,
                        "purpose": "PYTHON_RUN",
                        "evidence_scope": "storage flow only",
                        "inputs": [
                            {"path": "main.py", "role": "SOURCE", "object_version_id": revision}
                        ],
                        "entrypoint": "main.py",
                        "limits": limits.model_dump(),
                    },
                },
            )
            assert response.status_code == 201, response.text
            response = client.post("/internal/verification/claim", headers=private)
            assert response.status_code == 200, response.text
            claim = response.json()
            base = f"/internal/verification/jobs/{claim['job_id']}/attempts/{claim['attempt_id']}"
            source = client.get(
                f"{base}/inputs/0", headers=private, params={"generation": claim["generation"]}
            )
            assert source.status_code == 200 and source.content == b"print(1)"
            data = b"retained result, not mathematical assurance"
            declaration = {
                "generation": claim["generation"],
                "path": "result.txt",
                "role": "OUTPUT",
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_length": len(data),
            }
            response = client.put(
                f"{base}/outputs", headers=private, params=declaration, content=data
            )
            assert response.status_code == 200, response.text
            artifact_id = response.json()["artifact_id"]
            payload = {
                "job_id": claim["job_id"],
                "attempt_id": claim["attempt_id"],
                "generation": claim["generation"],
                "outcome": "COMPLETED",
                "exit_code": 0,
                "diagnostic_code": "NONE",
                "outputs": [
                    {key: value for key, value in declaration.items() if key != "generation"}
                    | {"artifact_id": artifact_id}
                ],
            }
            response = client.post("/internal/verification/complete", headers=private, json=payload)
            assert response.status_code == 200, response.text
            assert response.json()["state"] == "COMPLETED"
            replay = client.post("/internal/verification/complete", headers=private, json=payload)
            assert replay.json() == response.json()
            from uuid import UUID

            from polycolab.db.models import SqlArtifact

            with app.state.session_factory() as session:
                artifact = session.get(SqlArtifact, UUID(artifact_id))
                assert artifact is not None and artifact.state.value == "COMMITTED"
                storage_key = artifact.storage_key
            storage.delete(storage_key)
    finally:
        app.state.engine.dispose()

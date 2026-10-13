"""Version-reference migration preserves jobs, validation and controller identity."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_research_domain import headers
from test_verification import admit, completion, setup_job

from polycolab.db.models import SqlVerificationJob
from polycolab.verification.contracts import request_digest
from polycolab.verification.version_contracts import (
    VersionControllerClaim,
    VersionJobRead,
    VersionJobSubmission,
)


def test_version_job_roundtrip_preserves_stored_specification_and_controller_identity(
    client: TestClient,
) -> None:
    app, user_id, submission = setup_job(client)
    original = admit(app, user_id, submission, "retained-job")
    wire = VersionJobSubmission.from_stored(submission)
    assert wire.historical_command() == submission
    assert request_digest(wire.historical_command()) == request_digest(submission)
    url = f"/api/v1/projects/{submission.project_id}/verification-jobs"
    payload = {
        "retry_key": "retained-job",
        "submission": wire.model_dump(mode="json", by_alias=True),
    }
    replay = client.post(url, headers=headers("owner"), json=payload)
    assert replay.status_code == 201, replay.text
    assert VersionJobRead.model_validate(replay.json()).historical_value() == original
    assert replay.json()["submission"]["inputs"][0]["object_version_id"] == str(
        submission.inputs[0].revision_id
    )
    assert "revision_id" not in replay.json()["submission"]["inputs"][0]
    assert client.get(f"{url}/{original.id}", headers=headers("owner")).json() == replay.json()
    assert (
        client.post(
            url,
            headers=headers("owner"),
            json={"retry_key": "legacy", "submission": submission.model_dump(mode="json")},
        ).status_code
        == 422
    )
    app.state.settings.feature_verification_execution_enabled = True
    private = headers("test-controller-only")
    response = client.post("/internal/verification/claim", headers=private)
    assert response.status_code == 200, response.text
    leased = VersionControllerClaim.model_validate(response.json())
    assert leased.submission == wire
    assert leased.manifest_digest == original.manifest_digest
    assert leased.historical_value().submission == submission
    binding = {
        "job_id": str(leased.job_id),
        "attempt_id": str(leased.attempt_id),
        "generation": leased.generation,
    }
    renewed = client.post("/internal/verification/renew", headers=private, json=binding)
    assert renewed.status_code == 200, renewed.text
    assert renewed.json()["submission"] == wire.model_dump(mode="json", by_alias=True)
    finished = client.post(
        "/internal/verification/complete",
        headers=private,
        json=completion(leased).model_dump(mode="json"),
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["submission"] == wire.model_dump(mode="json", by_alias=True)
    assert finished.json()["manifest_digest"] == original.manifest_digest
    with app.state.session_factory() as db:
        stored = db.get(SqlVerificationJob, UUID(replay.json()["id"]))
        assert stored is not None
        assert stored.request_digest == request_digest(submission)
        assert db.query(SqlVerificationJob).count() == 1


def test_live_submission_retains_validation_and_rejects_legacy_nested_references(
    client: TestClient,
) -> None:
    _, _, original = setup_job(client)
    value = VersionJobSubmission.from_stored(original).model_dump(mode="json")
    for invalid in (
        {
            **value,
            "inputs": [
                {**value["inputs"][0], "revision_id": str(original.work_target_revision_id)}
            ],
        },
        {**value, "inputs": [{**value["inputs"][0], "artifact_id": str(original.environment_id)}]},
        {**value, "inputs": [value["inputs"][0], value["inputs"][0]]},
        {**value, "entrypoint": "../main.py"},
        {**value, "arguments": ["invalid\x00argument"]},
        {**value, "purpose": "CERTIFICATE_VERIFICATION"},
    ):
        with pytest.raises(ValidationError):
            VersionJobSubmission.model_validate(invalid)

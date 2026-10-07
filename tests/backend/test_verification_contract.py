from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from polycolab.verification.contracts import (
    ControllerCompletion,
    InputReference,
    JobSubmission,
    ResourceLimits,
    request_digest,
    validate_completion_limits,
)


def submission() -> dict[str, Any]:
    return {
        "project_id": str(uuid4()),
        "work_target_revision_id": str(uuid4()),
        "environment_id": str(uuid4()),
        "purpose": "PYTHON_RUN",
        "evidence_scope": "Search integers 1 through 100 for a counterexample",
        "inputs": [{"path": "src/main.py", "role": "SOURCE", "revision_id": str(uuid4())}],
        "entrypoint": "src/main.py",
        "seed": 7,
        "limits": {
            "cpu_count": 1,
            "cpu_seconds": 10,
            "wall_seconds": 30,
            "memory_bytes": 64 * 1024 * 1024,
            "process_count": 16,
            "disk_bytes": 4 * 1024 * 1024,
            "output_bytes": 1024 * 1024,
            "log_bytes": 65536,
            "output_files": 4,
        },
    }


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../main.py",
        "src/../main.py",
        "src/./main.py",
        "src//main.py",
        "src/main.py/",
        "C:\\main.py",
        "main.py\x00",
        ".polycolab/token",
        "%2e%2e/main.py",
    ],
)
def test_input_paths_reject_escape_and_aliases(path: str) -> None:
    with pytest.raises(ValidationError):
        InputReference(path=path, role="SOURCE", revision_id=uuid4())


def test_each_input_has_exactly_one_typed_identity() -> None:
    for identifiers in [{}, {"revision_id": uuid4(), "artifact_id": uuid4()}]:
        with pytest.raises(ValidationError):
            InputReference.model_validate({"path": "main.py", "role": "SOURCE", **identifiers})
    assert InputReference(path="data.txt", role="INPUT", artifact_id=uuid4()).revision_id is None


@pytest.mark.parametrize("path", ["src/main.py", "src", "src/main.py/dependency.py"])
def test_duplicate_and_file_directory_collisions(path: str) -> None:
    payload = submission()
    payload["inputs"].append({"path": path, "role": "INPUT", "artifact_id": str(uuid4())})
    with pytest.raises(ValidationError):
        JobSubmission.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cpu_count", 0),
        ("cpu_seconds", -1),
        ("wall_seconds", 0),
        ("wall_seconds", 3601),
        ("memory_bytes", 0),
        ("process_count", 0),
        ("disk_bytes", 0),
        ("output_bytes", 16 * 1024 * 1024 + 1),
        ("log_bytes", -1),
        ("output_files", 65),
        ("wall_seconds", True),
        ("cpu_count", "1"),
        ("cpu_seconds", float("inf")),
    ],
)
def test_resource_requests_are_finite_and_typed(field: str, value: object) -> None:
    payload = submission()["limits"]
    payload[field] = value
    with pytest.raises(ValidationError):
        ResourceLimits.model_validate(payload)


def test_resource_request_must_be_explicit_and_coherent() -> None:
    with pytest.raises(ValidationError):
        ResourceLimits.model_validate({})
    values = submission()["limits"]
    values["cpu_seconds"] = values["wall_seconds"] + 1
    with pytest.raises(ValidationError, match="CPU budget"):
        ResourceLimits.model_validate(values)
    values["cpu_seconds"] = 10
    values["disk_bytes"] = values["output_bytes"]
    with pytest.raises(ValidationError, match="writable disk"):
        ResourceLimits.model_validate(values)


def test_source_and_separate_certificate_are_required() -> None:
    payload = submission()
    payload["entrypoint"] = "absent.py"
    with pytest.raises(ValidationError, match="explicit source"):
        JobSubmission.model_validate(payload)
    payload["entrypoint"] = "src/main.py"
    payload["purpose"] = "CERTIFICATE_VERIFICATION"
    with pytest.raises(ValidationError, match="separate certificate"):
        JobSubmission.model_validate(payload)
    payload["inputs"].append(
        {"path": "certificate.json", "role": "CERTIFICATE", "artifact_id": str(uuid4())}
    )
    assert JobSubmission.model_validate(payload).purpose == "CERTIFICATE_VERIFICATION"


def test_client_cannot_supply_images_credentials_or_inline_source() -> None:
    for name in ["image", "controller_token", "database_url", "code", "shell_command"]:
        payload = submission()
        payload[name] = "untrusted"
        with pytest.raises(ValidationError, match="Extra inputs"):
            JobSubmission.model_validate(payload)


def test_manifest_is_immutable_and_digest_binds_exact_inputs_and_parameters() -> None:
    payload = submission()
    original = JobSubmission.model_validate(payload)
    assert request_digest(original) == request_digest(
        JobSubmission.model_validate_json(original.model_dump_json())
    )
    with pytest.raises(ValidationError, match="frozen"):
        original.seed = 9
    with pytest.raises(ValidationError, match="frozen"):
        original.inputs[0].path = "other.py"
    payload["seed"] = 8
    assert request_digest(JobSubmission.model_validate(payload)) != request_digest(original)
    payload["seed"] = 7
    payload["inputs"][0]["revision_id"] = str(uuid4())
    assert request_digest(JobSubmission.model_validate(payload)) != request_digest(original)


def completion() -> dict[str, Any]:
    return {
        "job_id": str(uuid4()),
        "attempt_id": str(uuid4()),
        "generation": 1,
        "outcome": "COMPLETED",
        "exit_code": 0,
        "diagnostic_code": "NONE",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"generation": 0},
        {"generation": True},
        {"exit_code": 1},
        {"diagnostic_code": "PROGRAM_ERROR"},
        {"outcome": "FAILED"},
        {"raw_logs": "private data"},
    ],
)
def test_malformed_completion_cannot_look_successful(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ControllerCompletion.model_validate({**completion(), **overrides})


def test_completion_digest_binds_generation_and_attempt() -> None:
    payload = completion()
    first = request_digest(ControllerCompletion.model_validate(payload))
    payload["generation"] = 2
    assert request_digest(ControllerCompletion.model_validate(payload)) != first
    payload["generation"] = 1
    payload["attempt_id"] = str(uuid4())
    assert request_digest(ControllerCompletion.model_validate(payload)) != first


def test_completion_outputs_are_bounded_and_unique() -> None:
    payload = completion()
    output = {
        "artifact_id": str(uuid4()),
        "path": "result.json",
        "role": "OUTPUT",
        "sha256": "a" * 64,
        "byte_length": 16 * 1024 * 1024,
    }
    payload["outputs"] = [output, output]
    with pytest.raises(ValidationError):
        ControllerCompletion.model_validate(payload)
    payload["outputs"] = [output, {**output, "artifact_id": str(uuid4()), "path": "other.json"}]
    with pytest.raises(ValidationError, match="total outputs"):
        ControllerCompletion.model_validate(payload)


@pytest.mark.parametrize("role,byte_length", [("OUTPUT", 1024 * 1024 + 1), ("DIAGNOSTIC", 65537)])
def test_completion_cannot_exceed_job_specific_limits(role: str, byte_length: int) -> None:
    payload = completion()
    payload["outputs"] = [
        {
            "artifact_id": str(uuid4()),
            "path": "result",
            "role": role,
            "sha256": "0" * 64,
            "byte_length": byte_length,
        }
    ]
    with pytest.raises(ValueError, match="admitted byte"):
        validate_completion_limits(
            ControllerCompletion.model_validate(payload),
            ResourceLimits.model_validate(submission()["limits"]),
        )


def test_empty_files_still_consume_the_admitted_file_budget() -> None:
    payload = completion()
    payload["outputs"] = [
        {
            "artifact_id": str(uuid4()),
            "path": f"empty-{i}",
            "role": "OUTPUT",
            "sha256": "0" * 64,
            "byte_length": 0,
        }
        for i in range(5)
    ]
    limits = ResourceLimits.model_validate(submission()["limits"])
    with pytest.raises(ValueError, match="admitted file"):
        validate_completion_limits(ControllerCompletion.model_validate(payload), limits)
    payload["outputs"] = payload["outputs"][:4]
    validate_completion_limits(ControllerCompletion.model_validate(payload), limits)

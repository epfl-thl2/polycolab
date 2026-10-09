"""Bounded execution contracts shared by future APIs and the private controller.

No database/runtime imports: validation neither authorizes inputs nor executes
source. Domain services must resolve exact IDs, reserve budgets, verify actual
bytes and fence the current lease before accepting any controller observation.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MiB = 1024 * 1024
GiB = 1024 * MiB
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
RelativePath = Annotated[str, Field(min_length=1, max_length=240, pattern=r"^[A-Za-z0-9_./-]+$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def validate_path(value: str) -> str:
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts) or parts[0] == ".polycolab":
        raise ValueError("path must be relative, normalized and outside controller metadata")
    return value


def _distinct_paths(paths: tuple[str, ...]) -> None:
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            raise ValueError("duplicate file path")
        seen.add(path)
    for path in paths:
        parts = path.split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            raise ValueError("a file path cannot also be a parent directory")


class ResourceLimits(Contract):
    """Explicit finite requests; deployment/environment policy may lower ceilings.

    These are contract bounds, not measured deployment capacity or an admission
    grant. No zero/unlimited sentinel and no implicit default resource request.
    """

    cpu_count: int = Field(strict=True, ge=1, le=8)
    cpu_seconds: int = Field(strict=True, ge=1, le=28_800)
    wall_seconds: int = Field(strict=True, ge=1, le=3600)
    memory_bytes: int = Field(strict=True, ge=16 * MiB, le=16 * GiB)
    process_count: int = Field(strict=True, ge=1, le=256)
    disk_bytes: int = Field(strict=True, ge=MiB, le=16 * GiB)
    output_bytes: int = Field(strict=True, ge=0, le=16 * MiB)
    log_bytes: int = Field(strict=True, ge=0, le=MiB)
    output_files: int = Field(strict=True, ge=0, le=64)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.cpu_seconds > self.cpu_count * self.wall_seconds:
            raise ValueError("CPU budget exceeds available CPU/wall-time product")
        if self.output_bytes + self.log_bytes > self.disk_bytes:
            raise ValueError("output and log ceilings must fit writable disk")
        return self


class InputReference(Contract):
    path: RelativePath
    role: Literal["SOURCE", "INPUT", "CERTIFICATE"]
    revision_id: UUID | None = None
    artifact_id: UUID | None = None

    _path = field_validator("path")(validate_path)

    @model_validator(mode="after")
    def exactly_one_identity(self) -> Self:
        if (self.revision_id is None) == (self.artifact_id is None):
            raise ValueError("input requires exactly one revision or artifact identity")
        return self


class JobPurpose(StrEnum):
    LEAN_CHECK = "LEAN_CHECK"
    PYTHON_RUN = "PYTHON_RUN"
    CERTIFICATE_GENERATION = "CERTIFICATE_GENERATION"
    CERTIFICATE_VERIFICATION = "CERTIFICATE_VERIFICATION"


class JobSubmission(Contract):
    version: Literal[1] = 1
    project_id: UUID
    work_target_revision_id: UUID
    research_attempt_revision_id: UUID | None = None
    environment_id: UUID
    purpose: JobPurpose
    evidence_scope: str = Field(min_length=1, max_length=4000)
    inputs: tuple[InputReference, ...] = Field(min_length=1, max_length=128)
    entrypoint: RelativePath
    # Arguments are an argv sequence, never a shell command. The runner's fixed
    # invocation determines how they are passed to untrusted submitted source.
    arguments: tuple[Annotated[str, Field(max_length=1024)], ...] = Field(default=(), max_length=32)
    seed: int | None = Field(default=None, strict=True, ge=0, le=2**63 - 1)
    limits: ResourceLimits

    _entrypoint = field_validator("entrypoint")(validate_path)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _distinct_paths(tuple(item.path for item in self.inputs))
        if not any(item.path == self.entrypoint and item.role == "SOURCE" for item in self.inputs):
            raise ValueError("entrypoint must name an explicit source input")
        if self.purpose == JobPurpose.CERTIFICATE_VERIFICATION and not any(
            item.role == "CERTIFICATE" for item in self.inputs
        ):
            raise ValueError("certificate verification requires a separate certificate input")
        if any("\x00" in argument for argument in self.arguments):
            raise ValueError("arguments cannot contain NUL")
        if not self.evidence_scope.strip():
            raise ValueError("evidence scope cannot be blank")
        return self


class VerificationJobReference(Contract):
    job_id: UUID


class AttemptBinding(Contract):
    job_id: UUID
    attempt_id: UUID
    generation: int = Field(strict=True, ge=1, le=2**31 - 1)


class OutputReference(Contract):
    artifact_id: UUID
    path: RelativePath
    sha256: Digest
    byte_length: int = Field(strict=True, ge=0, le=16 * MiB)
    role: Literal["OUTPUT", "CERTIFICATE", "DIAGNOSTIC"]

    _path = field_validator("path")(validate_path)


class ControllerCompletion(AttemptBinding):
    outcome: Literal["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]
    exit_code: int | None = Field(default=None, strict=True, ge=-255, le=255)
    # Logs travel as bounded verified artifacts, not arbitrary large JSON strings.
    diagnostic_code: Literal[
        "NONE", "PROGRAM_ERROR", "RESOURCE_LIMIT", "CANCELLED", "LEASE_LOST", "RUNTIME_UNAVAILABLE"
    ]
    outputs: tuple[OutputReference, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _distinct_paths(tuple(item.path for item in self.outputs))
        if len({item.artifact_id for item in self.outputs}) != len(self.outputs):
            raise ValueError("duplicate output artifact")
        if sum(item.byte_length for item in self.outputs) > 16 * MiB:
            raise ValueError("total outputs exceed contract ceiling")
        if self.outcome == "COMPLETED" and (self.exit_code != 0 or self.diagnostic_code != "NONE"):
            raise ValueError("completion requires a zero exit and no failure diagnostic")
        if self.outcome != "COMPLETED" and self.diagnostic_code == "NONE":
            raise ValueError("unsuccessful completion requires a diagnostic")
        return self


def request_digest(payload: JobSubmission | ControllerCompletion) -> str:
    """Versioned replay identity; a digest is never authorization or byte evidence."""
    encoded = json.dumps(
        {
            "contract": type(payload).__name__,
            "version": 1,
            "payload": payload.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


class VerificationInputInvalid(ValueError):
    pass


def validate_completion_limits(completion: ControllerCompletion, limits: ResourceLimits) -> None:
    """Reject declared output overflow before byte retrieval/commit.

    This does not establish honesty of controller declarations: the service must
    verify staged bytes and their attempt binding against these same limits.
    Diagnostic artifacts count toward log bytes; all files count toward the file
    ceiling, including empty files. This prevents zero-byte file-count overflow.
    """
    if len(completion.outputs) > limits.output_files:
        raise VerificationInputInvalid("outputs exceed admitted file count")
    output_bytes = sum(item.byte_length for item in completion.outputs if item.role != "DIAGNOSTIC")
    log_bytes = sum(item.byte_length for item in completion.outputs if item.role == "DIAGNOSTIC")
    if output_bytes > limits.output_bytes or log_bytes > limits.log_bytes:
        raise VerificationInputInvalid("outputs exceed admitted byte limits")


class JobSubmitRequest(Contract):
    retry_key: str = Field(min_length=1, max_length=200)
    submission: JobSubmission


class RetryRequest(Contract):
    retry_key: str = Field(min_length=1, max_length=200)


class ResultRead(Contract):
    id: UUID
    attempt_id: UUID
    outcome: str
    diagnostic_summary: dict[str, object]
    created_at: datetime
    outputs: tuple[OutputReference, ...]


class AttemptRead(Contract):
    id: UUID
    generation: int
    state: str
    started_at: datetime
    terminal_at: datetime | None


class JobRead(Contract):
    id: UUID
    submission: JobSubmission
    manifest_digest: Digest
    state: str
    generation: int
    event_sequence: int
    deadline_at: datetime
    terminal_reason: str | None
    attempts: tuple[AttemptRead, ...]
    results: tuple[ResultRead, ...]


class EventRead(Contract):
    sequence: int
    attempt_id: UUID | None
    event_type: str
    created_at: datetime


class ControllerClaim(AttemptBinding):
    lease_expires_at: datetime
    execution_deadline_at: datetime
    submission: JobSubmission
    manifest_digest: Digest
    image_digest: Digest
    toolchain_version: str
    dependency_lock_digest: Digest
    build_digest: Digest
    platform_identity: str


class OutputStageRequest(AttemptBinding):
    path: RelativePath
    role: Literal["OUTPUT", "CERTIFICATE", "DIAGNOSTIC"]
    sha256: Digest
    byte_length: int = Field(strict=True, ge=0, le=16 * MiB)

    _path = field_validator("path")(validate_path)

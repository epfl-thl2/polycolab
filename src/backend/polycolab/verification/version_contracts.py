"""Live object-version job contracts over unchanged stored execution specifications."""

from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from polycolab.verification.contracts import (
    AttemptBinding,
    AttemptRead,
    Contract,
    ControllerClaim,
    Digest,
    InputReference,
    JobPurpose,
    JobRead,
    JobSubmission,
    RelativePath,
    ResourceLimits,
    ResultRead,
)


class VersionInputReference(Contract):
    path: RelativePath
    role: Literal["SOURCE", "INPUT", "CERTIFICATE"]
    object_version_id: UUID | None = None
    artifact_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        self.historical_command()
        return self

    def historical_command(self) -> InputReference:
        return InputReference(
            path=self.path,
            role=self.role,
            revision_id=self.object_version_id,
            artifact_id=self.artifact_id,
        )

    @classmethod
    def from_stored(cls, value: InputReference) -> Self:
        return cls(
            path=value.path,
            role=value.role,
            object_version_id=value.revision_id,
            artifact_id=value.artifact_id,
        )


class VersionJobSubmission(Contract):
    version: Literal[1] = 1
    project_id: UUID
    work_target_object_version_id: UUID
    research_attempt_object_version_id: UUID | None = None
    environment_id: UUID
    purpose: JobPurpose
    evidence_scope: str = Field(min_length=1, max_length=4000)
    inputs: tuple[VersionInputReference, ...] = Field(min_length=1, max_length=128)
    entrypoint: RelativePath
    arguments: tuple[Annotated[str, Field(max_length=1024)], ...] = Field(default=(), max_length=32)
    seed: int | None = Field(default=None, strict=True, ge=0, le=2**63 - 1)
    limits: ResourceLimits

    @model_validator(mode="after")
    def coherent(self) -> Self:
        # One source of validation for path collisions, entrypoint, purpose and limits.
        self.historical_command()
        return self

    def historical_command(self) -> JobSubmission:
        return JobSubmission(
            **self.model_dump(
                exclude={
                    "work_target_object_version_id",
                    "research_attempt_object_version_id",
                    "inputs",
                }
            ),
            work_target_revision_id=self.work_target_object_version_id,
            research_attempt_revision_id=self.research_attempt_object_version_id,
            inputs=tuple(item.historical_command() for item in self.inputs),
        )

    @classmethod
    def from_stored(cls, value: JobSubmission) -> Self:
        return cls(
            **value.model_dump(
                exclude={"work_target_revision_id", "research_attempt_revision_id", "inputs"}
            ),
            work_target_object_version_id=value.work_target_revision_id,
            research_attempt_object_version_id=value.research_attempt_revision_id,
            inputs=tuple(VersionInputReference.from_stored(item) for item in value.inputs),
        )


class VersionJobSubmitRequest(Contract):
    retry_key: str = Field(min_length=1, max_length=200)
    submission: VersionJobSubmission


class VersionJobRead(Contract):
    id: UUID
    submission: VersionJobSubmission
    manifest_digest: Digest
    state: str
    generation: int
    event_sequence: int
    deadline_at: datetime
    terminal_reason: str | None
    attempts: tuple[AttemptRead, ...]
    results: tuple[ResultRead, ...]

    @classmethod
    def from_stored(cls, value: JobRead) -> Self:
        return cls(
            **value.model_dump(exclude={"submission"}),
            submission=VersionJobSubmission.from_stored(value.submission),
        )

    def historical_value(self) -> JobRead:
        return JobRead(
            **self.model_dump(exclude={"submission"}),
            submission=self.submission.historical_command(),
        )


class VersionControllerClaim(AttemptBinding):
    lease_expires_at: datetime
    execution_deadline_at: datetime
    submission: VersionJobSubmission
    manifest_digest: Digest
    image_digest: Digest
    toolchain_version: str
    dependency_lock_digest: Digest
    build_digest: Digest
    platform_identity: str

    @classmethod
    def from_stored(cls, value: ControllerClaim) -> Self:
        return cls(
            **value.model_dump(exclude={"submission"}),
            submission=VersionJobSubmission.from_stored(value.submission),
        )

    def historical_value(self) -> ControllerClaim:
        return ControllerClaim(
            **self.model_dump(exclude={"submission"}),
            submission=self.submission.historical_command(),
        )

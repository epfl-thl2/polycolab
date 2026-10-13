"""Browser and private-worker document build contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from polycolab.entities.document_builds import BuildStatus, Engine
from polycolab.projects.git_storage import oid, path_name


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    main_file: str = Field(min_length=1, max_length=1000)
    engine: Engine = "pdflatex"
    _revision = field_validator("revision")(oid)
    _path = field_validator("main_file")(path_name)


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    worktree_id: UUID
    revision: str
    main_file: str
    engine: Engine
    status: BuildStatus
    created_at: datetime
    expires_at: datetime
    error: str | None
    pdf_available: bool = False
    log_available: bool = False


class BuildList(BaseModel):
    available: bool
    builds: list[BuildRead]


class WorkerReady(BaseModel):
    image: str = Field(max_length=300)


class WorkerClaim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=200)


class BuildAttempt(BaseModel):
    generation: UUID


class BuildCompletion(BuildAttempt):
    status: Literal["succeeded", "failed", "timed_out"]
    error: (
        Literal["latex_compile_failed", "latex_timeout", "latex_output_limit", "latex_worker_error"]
        | None
    ) = None


class BuildClaimRead(BaseModel):
    id: UUID
    generation: UUID
    main_file: str
    engine: Engine
    image: str
    deadline: datetime
    input_sha256: str

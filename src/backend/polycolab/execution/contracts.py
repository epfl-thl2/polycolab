"""Database-free resource and path contracts for workspace execution."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

"""Immutable hosted engine configuration; contains no credentials."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from polycolab.verification.contracts import ResourceLimits


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    engine: Literal["codex"] = "codex"
    engine_version: Literal["0.154.0"] = "0.154.0"
    sandbox_backend: Literal["microsandbox", "gvisor"] = "microsandbox"
    sandbox_version: str = Field(
        default="0.6.18", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._+-]+$"
    )
    image: str = Field(pattern=r"^[^\s]+@sha256:[0-9a-f]{64}$")
    policy_version: Literal[1] = 1
    max_model_requests: int = Field(default=4, ge=1, le=16)
    max_output_tokens: int = Field(default=8192, ge=1, le=100_000)
    max_input_bytes: int = Field(default=262_144, ge=1, le=262_144)
    max_input_tokens: int = Field(default=262_144, ge=1)
    input_microusd_per_million_tokens: int = Field(default=10_000_000, ge=0)
    output_microusd_per_million_tokens: int = Field(default=30_000_000, ge=0)
    max_attempts: int = Field(default=2, ge=1, le=5)
    limits: ResourceLimits

    @property
    def round_cost_microusd(self) -> int:
        return (
            self.max_input_tokens * self.input_microusd_per_million_tokens
            + self.max_output_tokens * self.output_microusd_per_million_tokens
            + 999_999
        ) // 1_000_000

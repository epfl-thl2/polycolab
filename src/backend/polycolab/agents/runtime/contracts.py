"""Provider-neutral frames exchanged by the built-in runtime and model gateway."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

FinishReason = Literal["stop", "length", "tool_calls"]


@dataclass(frozen=True)
class ToolCallDelta:
    """A deliberately provider-id-free fragment of one OpenAI-compatible call."""

    index: int
    name: str | None = None
    arguments: str | None = None


@dataclass(frozen=True)
class ToolCall:
    """One fully assembled platform tool call, never exposed as a provider object."""

    index: int
    name: str
    arguments: str


@dataclass(frozen=True)
class Usage:
    """Validated provider usage; provider-specific fields are intentionally absent."""

    completion_tokens: int
    prompt_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelStreamFrame:
    """Allowlisted, provider-neutral model stream frame."""

    content: str | None = None
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
    tool_call_deltas: tuple[ToolCallDelta, ...] = ()


@dataclass(frozen=True)
class ModelTurn:
    """Bounded model input; a run grant is transported separately."""

    run_id: UUID
    model_id: str
    messages: list[dict[str, object]]
    max_output_tokens: int


class ModelGateway(Protocol):
    """Private model gateway used by workers; it never accepts a provider key."""

    def stream(self, turn: ModelTurn, *, grant: str) -> Iterator[ModelStreamFrame]: ...

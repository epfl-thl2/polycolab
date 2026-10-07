"""Exact versioned attempt cost arithmetic for the pending shared scheduler.

This is not an allocator and is not wired to admission before its schema lands.
"""

from dataclasses import dataclass

from polycolab.verification.contracts import ResourceLimits

MAX_COUNTER = 2**63 - 1


def _positive(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_COUNTER:
        raise ValueError("scheduling value must be a positive signed-64-bit integer")


@dataclass(frozen=True)
class VerificationCostPolicy:
    version: int
    cpu_seconds_per_unit: int
    memory_byte_seconds_per_unit: int
    wall_seconds_per_unit: int

    def __post_init__(self) -> None:
        for value in (
            self.version,
            self.cpu_seconds_per_unit,
            self.memory_byte_seconds_per_unit,
            self.wall_seconds_per_unit,
        ):
            _positive(value)


@dataclass(frozen=True)
class AgentCostPolicy:
    version: int
    model_tokens_per_unit: int
    provider_cost_microusd_per_unit: int
    wall_seconds_per_unit: int

    def __post_init__(self) -> None:
        for value in (
            self.version,
            self.model_tokens_per_unit,
            self.provider_cost_microusd_per_unit,
            self.wall_seconds_per_unit,
        ):
            _positive(value)


def reserved_agent_cost(
    *,
    model_tokens: int,
    provider_cost_microusd: int,
    wall_seconds: int,
    policy: AgentCostPolicy,
) -> int:
    """Normalize immutable per-attempt agent ceilings, not live settings.

    Provider currency is integer micro-USD, never a floating-point dollar amount.
    Historical runs lacking these exact limits must not call this with guessed
    defaults. Admission persists the result and policy version atomically with
    the work item; each subsequent attempt receives a separate charge.
    """
    values = (
        (model_tokens, policy.model_tokens_per_unit),
        (provider_cost_microusd, policy.provider_cost_microusd_per_unit),
        (wall_seconds, policy.wall_seconds_per_unit),
    )
    for value, _ in values:
        _positive(value)
    return max((value - 1) // divisor + 1 for value, divisor in values)


def reserved_cost(limits: ResourceLimits, policy: VerificationCostPolicy) -> int:
    """One attempt's maximum normalized resource share, rounded upward.

    Retries are charged separately. Do not multiply this cost by max_attempts:
    admission budget reservation and per-attempt scheduling charge are distinct.
    """
    values = (
        (limits.cpu_seconds, policy.cpu_seconds_per_unit),
        (limits.memory_bytes * limits.wall_seconds, policy.memory_byte_seconds_per_unit),
        (limits.wall_seconds, policy.wall_seconds_per_unit),
    )
    for value, _ in values:
        _positive(value)
    return max((value - 1) // divisor + 1 for value, divisor in values)


def advance_runtime(current: int, cost: int) -> int:
    """Advance an equal-weight durable counter without database overflow."""
    if type(current) is not int or not 0 <= current <= MAX_COUNTER:
        raise ValueError("invalid scheduling virtual runtime")
    _positive(cost)
    if current > MAX_COUNTER - cost:
        raise ValueError("scheduling virtual runtime exhausted")
    return current + cost

import pytest

from polycolab.execution.scheduling import (
    MAX_COUNTER,
    AgentCostPolicy,
    advance_runtime,
    reserved_agent_cost,
)


def test_virtual_runtime_uses_exact_integer_arithmetic() -> None:
    assert advance_runtime(2**53, 1) == 2**53 + 1
    assert advance_runtime(MAX_COUNTER - 1, 1) == MAX_COUNTER
    with pytest.raises(ValueError, match="exhausted"):
        advance_runtime(MAX_COUNTER, 1)


@pytest.mark.parametrize("current,cost", [(-1, 1), (True, 1), (0, 0), (0, True)])
def test_invalid_runtime_or_charge_fails_closed(current: int, cost: int) -> None:
    with pytest.raises(ValueError):
        advance_runtime(current, cost)


@pytest.mark.parametrize(
    "tokens,cost,wall,expected",
    [(11, 1, 1, 2), (1, 21, 1, 3), (1, 1, 31, 4), (1, 1, 1, 1)],
)
def test_agent_maximum_ceiling_share(tokens: int, cost: int, wall: int, expected: int) -> None:
    assert (
        reserved_agent_cost(
            model_tokens=tokens,
            provider_cost_microusd=cost,
            wall_seconds=wall,
            policy=AgentCostPolicy(1, 10, 10, 10),
        )
        == expected
    )


@pytest.mark.parametrize("invalid", [0, -1, True, MAX_COUNTER + 1])
def test_agent_rejects_invalid_limits_and_each_policy_field(invalid: int) -> None:
    for index in range(4):
        values = [1, 1, 1, 1]
        values[index] = invalid
        with pytest.raises(ValueError):
            AgentCostPolicy(*values)
    for field in ("model_tokens", "provider_cost_microusd", "wall_seconds"):
        limits = {"model_tokens": 1, "provider_cost_microusd": 1, "wall_seconds": 1}
        limits[field] = invalid
        with pytest.raises(ValueError):
            reserved_agent_cost(**limits, policy=AgentCostPolicy(1, 1, 1, 1))


def test_agent_large_integer_charge_is_exact_and_retry_is_separate() -> None:
    cost = reserved_agent_cost(
        model_tokens=MAX_COUNTER,
        provider_cost_microusd=1,
        wall_seconds=1,
        policy=AgentCostPolicy(1, 2, 1, 1),
    )
    assert cost == 2**62
    assert advance_runtime(0, cost) == cost
    with pytest.raises(ValueError, match="exhausted"):
        advance_runtime(cost, cost)

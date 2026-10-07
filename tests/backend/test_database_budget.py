"""Declared topology arithmetic and deployment wiring, not load acceptance."""

from pathlib import Path

import pytest

from polycolab.operations.database_budget import calculate, main


def test_multiple_process_classes_include_overflow_and_headroom() -> None:
    report = calculate(server_limit=100, reserved=10, headroom=10, pools=[(4, 5, 5), (2, 2, 0)])
    assert report.status == "CONFIGURATION_FITS"
    assert report.application_connections == 44
    assert report.unallocated_connections == 36


@pytest.mark.parametrize("limit", [59, 60])
def test_no_margin_or_overcommit_fails(limit: int) -> None:
    report = calculate(server_limit=limit, reserved=10, headroom=10, pools=[(4, 5, 5)])
    assert report.status == "BUDGET_EXCEEDED"


@pytest.mark.parametrize("pool", [(0, 5, 5), (1, 0, 0), (1, 5, -1), (True, 5, 5), (1, 1001, 0)])
def test_invalid_or_unlimited_pools_fail(pool: tuple[int, int, int]) -> None:
    with pytest.raises(ValueError):
        calculate(server_limit=100, reserved=10, headroom=10, pools=[pool])


def test_no_processes_or_no_maintenance_reserve_is_invalid() -> None:
    with pytest.raises(ValueError):
        calculate(server_limit=100, reserved=10, headroom=10, pools=[])
    with pytest.raises(ValueError):
        calculate(server_limit=100, reserved=10, headroom=0, pools=[(1, 5, 5)])


def test_cli_returns_failure_for_overcommit(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(
            ["--server-limit", "10", "--reserved", "3", "--headroom", "2", "--pool", "1", "5", "5"]
        )
        == 1
    )
    assert '"status": "BUDGET_EXCEEDED"' in capsys.readouterr().out


def test_compose_budgets_only_database_using_services() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "deploy/docker/compose.yml").read_text()
    api = compose.split("  api:\n", 1)[1].split("  community:\n", 1)[0]
    community = compose.split("  community:\n", 1)[1].split("  worker:\n", 1)[0]
    worker = compose.split("  worker:\n", 1)[1]
    for section in (api, community):
        for field in (
            "DATABASE_POOL_SIZE",
            "DATABASE_MAX_OVERFLOW",
            "DATABASE_POOL_TIMEOUT_SECONDS",
        ):
            assert f"      {field}:" in section
    assert "DATABASE_" not in worker
    for name in ("staging", "production"):
        example = (root / f"deploy/config/{name}.env.example").read_text()
        assert "DATABASE_POOL_SIZE=5" in example
        assert "DATABASE_MAX_OVERFLOW=5" in example
        assert "DATABASE_POOL_TIMEOUT_SECONDS=30" in example

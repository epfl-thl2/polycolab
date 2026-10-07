"""Offline connection-budget preflight; declared topology, not measured capacity."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BudgetReport:
    status: str
    application_connections: int
    reserved_connections: int
    maintenance_headroom: int
    server_limit: int
    unallocated_connections: int


def calculate(
    *, server_limit: int, reserved: int, headroom: int, pools: Sequence[tuple[int, int, int]]
) -> BudgetReport:
    def bounded(value: int, minimum: int, maximum: int) -> bool:
        return type(value) is int and minimum <= value <= maximum

    if (
        not bounded(server_limit, 1, 1_000_000)
        or not bounded(reserved, 0, 1_000_000)
        or not bounded(headroom, 1, 1_000_000)
        or not 1 <= len(pools) <= 100
    ):
        raise ValueError("invalid connection budget")
    application = 0
    for processes, size, overflow in pools:
        if (
            not bounded(processes, 1, 100_000)
            or not bounded(size, 1, 1000)
            or not bounded(overflow, 0, 1000)
        ):
            raise ValueError("invalid pool declaration")
        application += processes * (size + overflow)
    remaining = server_limit - reserved - headroom - application
    return BudgetReport(
        "CONFIGURATION_FITS" if remaining > 0 else "BUDGET_EXCEEDED",
        application,
        reserved,
        headroom,
        server_limit,
        remaining,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-limit", type=int, required=True)
    parser.add_argument("--reserved", type=int, required=True)
    parser.add_argument("--headroom", type=int, required=True)
    parser.add_argument(
        "--pool",
        type=int,
        nargs=3,
        action="append",
        required=True,
        metavar=("PROCESSES", "SIZE", "OVERFLOW"),
        help="repeat for every database-using process class, including rollout surge",
    )
    args = parser.parse_args(argv)
    try:
        report = calculate(
            server_limit=args.server_limit,
            reserved=args.reserved,
            headroom=args.headroom,
            pools=[tuple(pool) for pool in args.pool],
        )
    except ValueError:
        print(json.dumps({"status": "INVALID_BUDGET"}))
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0 if report.status == "CONFIGURATION_FITS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

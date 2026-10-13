"""Pinned guest bootstrap; wait for host containment verification before work."""

import os
import sys
from datetime import UTC, datetime


def main() -> int:
    deadline = datetime.fromisoformat(os.environ["POLYCOLAB_DEADLINE"])
    if datetime.now(UTC) >= deadline:
        return 1
    print('{"kind":"boot"}', flush=True)
    if sys.stdin.buffer.readline(4) != b"go\n" or datetime.now(UTC) >= deadline:
        return 1
    print('{"kind":"ready"}', flush=True)
    os.execv("/usr/bin/python3", ["/usr/bin/python3", "/opt/polycolab/guest_bridge.py"])


if __name__ == "__main__":
    raise SystemExit(main())

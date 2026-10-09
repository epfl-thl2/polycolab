"""Stable isolated execution-service command entrypoint."""

from polycolab.execution.service import main

if __name__ == "__main__":
    raise SystemExit(main())

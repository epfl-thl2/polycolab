"""Stable deployment-preflight command entrypoint."""

from polycolab.operations.deployment_preflight import main

if __name__ == "__main__":
    raise SystemExit(main())

"""One-shot deployment migration using the same settings and image as core."""

import subprocess

from polycolab.operations.deployment_preflight import main as preflight
from polycolab.platform.config import Environment, get_settings


def main() -> int:
    try:
        settings = get_settings()
    except Exception:
        print("deployment configuration: INVALID_SETTINGS")
        return 1
    if settings.app_env is Environment.PRODUCTION and preflight([]) != 0:
        return 1
    return subprocess.run(["alembic", "upgrade", "head"], check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

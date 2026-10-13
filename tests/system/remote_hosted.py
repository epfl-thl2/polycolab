"""Run only on an idle disposable executor host, invoked by run_hosted.py."""

from __future__ import annotations

import asyncio
import os
import sys
import tomllib
from pathlib import Path

from polycolab.execution.service import ServiceConfig, run


def main() -> None:
    root, identity, port = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    if not identity.isalnum():
        raise ValueError("invalid test identity")
    token = root / (identity + ".token")
    pid = root / (identity + ".pid")
    with open(token, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        stream.write(sys.stdin.readline().strip())
    pid.write_text(str(os.getpid()))
    try:
        config = ServiceConfig.model_validate(tomllib.loads((root / "controller.toml").read_text()))
        if config.backend != "gvisor":
            raise ValueError("gvisor test configuration required")
        config = config.model_copy(
            update={
                "api_url": f"http://127.0.0.1:{port}",
                "worker_id": identity,
                "agent_credential_file": str(token),
                "capacity": 1,
                "poll_seconds": 0.1,
            }
        )
        asyncio.run(run(config))
    finally:
        token.unlink(missing_ok=True)
        pid.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

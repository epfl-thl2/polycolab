"""Real local-mode browser smoke test using isolated temporary SQLite and blob data."""

from __future__ import annotations

import os
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/backend"))
from polycolab.operations.local_development import upgrade_database  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ready(url: str, processes: list[subprocess.Popen[bytes]]) -> None:
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("Local test service exited during startup")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Service did not become ready: {url}")


def main() -> int:
    processes: list[subprocess.Popen[bytes]] = []
    with tempfile.TemporaryDirectory(prefix="polycolab-local-smoke-") as temporary:
        directory = Path(temporary)
        database = directory / "research.db"
        upgrade_database(database)
        api_port, web_port = free_port(), free_port()
        origin = f"http://127.0.0.1:{web_port}"
        env = {
            **os.environ,
            "APP_ENV": "local",
            "AUTH_MODE": "local",
            "DATABASE_URL": f"sqlite+pysqlite:///{database}",
            "ARTIFACT_LOCAL_DIRECTORY": str(directory / "artifacts"),
            "REGISTRATION_MODE": "open",
            "PUBLIC_APP_ORIGIN": origin,
            "POLYCOLAB_API_PROXY_TARGET": f"http://127.0.0.1:{api_port}",
            "LOCAL_MODE_URL": origin,
            "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(24),
        }
        try:
            subprocess.run(
                [sys.executable, "-m", "polycolab.bootstrap_admin"],
                cwd=ROOT / "src/backend",
                env=env,
                check=True,
            )
            commands = [
                (
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "polycolab.main:app",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(api_port),
                    ],
                    ROOT / "src/backend",
                ),
                (
                    [
                        "pnpm",
                        "--filter",
                        "@polycolab/web",
                        "run",
                        "dev",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(web_port),
                        "--strictPort",
                    ],
                    ROOT,
                ),
            ]
            for command, cwd in commands:
                processes.append(
                    subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
                )
            ready(f"http://127.0.0.1:{api_port}/health/ready", processes)
            ready(origin, processes)
            return subprocess.run(
                [
                    "pnpm",
                    "--filter",
                    "@polycolab/web",
                    "exec",
                    "playwright",
                    "test",
                    "--config",
                    "../../tests/web/browser/local-mode.config.ts",
                ],
                cwd=ROOT,
                env=env,
            ).returncode
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
            for process in processes:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


if __name__ == "__main__":
    raise SystemExit(main())

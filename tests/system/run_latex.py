"""Real browser → FastAPI → PostgreSQL/Garage → Docker TeX Live acceptance.

Set POLYCOLAB_LATEX_IMAGE to the immutable image built from deploy/latex.
All service processes, databases, repositories, and buckets are disposable.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

from run_local_mode import free_port

from polycolab.document_builds.worker import preflight, reconcile

ROOT = Path(__file__).resolve().parents[2]


def ready(url: str, processes: list[subprocess.Popen[bytes]]) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("LaTeX test service exited during startup")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("LaTeX test service startup timed out")


def main() -> int:
    image = os.environ["POLYCOLAB_LATEX_IMAGE"]
    preflight(image)
    identity = "latex-test-" + uuid4().hex[:12]
    compose = [
        "docker",
        "compose",
        "-p",
        identity,
        "-f",
        str(ROOT / "tests/system/workspace-compose.yaml"),
    ]
    processes: list[subprocess.Popen[bytes]] = []
    label = ""
    with (
        tempfile.TemporaryDirectory(prefix="polycolab-latex-") as temporary,
        tempfile.TemporaryDirectory(
            prefix=".svelte-kit-test-", dir=ROOT / "src/web"
        ) as web_temporary,
    ):
        directory = Path(temporary)
        with (directory / "services.log").open("w+b") as diagnostics:

            def command(args: list[str], **kwargs):
                return subprocess.run(
                    args, check=True, stdout=diagnostics, stderr=diagnostics, timeout=180, **kwargs
                )

            try:
                print("Starting disposable PostgreSQL and Garage", flush=True)
                command(compose + ["up", "-d", "--wait"])

                def port(service: str, internal: str) -> str:
                    return (
                        subprocess.check_output(compose + ["port", service, internal], text=True)
                        .strip()
                        .rsplit(":", 1)[1]
                    )

                pg_port, garage_port = port("postgres", "5432"), port("garage", "3900")
                api_port, web_port = free_port(), free_port()
                api_url, origin = f"http://127.0.0.1:{api_port}", f"http://127.0.0.1:{web_port}"
                token = secrets.token_urlsafe(32)
                env = {
                    **os.environ,
                    "APP_ENV": "local",
                    "AUTH_MODE": "local",
                    "REGISTRATION_MODE": "open",
                    "BOOTSTRAP_ADMIN_PASSWORD": secrets.token_urlsafe(24),
                    "PUBLIC_APP_ORIGIN": origin,
                    "ALLOWED_ORIGINS": json.dumps([origin]),
                    "DATABASE_URL": f"postgresql+psycopg://research:research-test-only@127.0.0.1:{pg_port}/research",
                    "PROJECT_REPOSITORY_DIRECTORY": str(directory / "repos"),
                    "ARTIFACT_S3_ENDPOINT": f"http://127.0.0.1:{garage_port}",
                    "ARTIFACT_S3_BUCKET": "research-artifacts",
                    "ARTIFACT_S3_REGION": "garage",
                    "ARTIFACT_S3_ACCESS_KEY": "GK0123456789abcdef0123456789",
                    "ARTIFACT_S3_SECRET_KEY": "0123456789abcdef" * 4,
                    "LATEX_IMAGE": image,
                    "LATEX_WORKER_TOKEN": token,
                    "FEATURE_AGENT_EXECUTION_ENABLED": "false",
                    "FEATURE_VERIFICATION_EXECUTION_ENABLED": "false",
                    "POLYCOLAB_API_PROXY_TARGET": api_url,
                    "LOCAL_MODE_URL": origin,
                    "POLYCOLAB_SVELTE_OUT_DIR": Path(web_temporary).name,
                    "POLYCOLAB_LATEX_BROWSER": "1",
                }
                command(
                    [sys.executable, "-m", "alembic", "upgrade", "head"],
                    cwd=ROOT / "src/backend",
                    env=env,
                )
                command(
                    [sys.executable, "-m", "polycolab.bootstrap_admin"],
                    cwd=ROOT / "src/backend",
                    env=env,
                )
                for args, cwd in (
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
                            "--no-access-log",
                        ],
                        ROOT / "src/backend",
                    ),
                    (
                        [
                            "node",
                            "node_modules/vite/bin/vite.js",
                            "--host",
                            "127.0.0.1",
                            "--port",
                            str(web_port),
                            "--strictPort",
                        ],
                        ROOT / "src/web",
                    ),
                ):
                    processes.append(
                        subprocess.Popen(
                            args,
                            cwd=cwd,
                            env=env,
                            stdout=diagnostics,
                            stderr=diagnostics,
                            start_new_session=True,
                        )
                    )
                ready(api_url + "/health/ready", processes)
                ready(origin, processes)
                # The controller receives no database or object-storage environment.
                worker_env = {
                    key: value
                    for key, value in os.environ.items()
                    if key in {"PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT"}
                }
                worker_env.update(
                    LATEX_IMAGE=image, LATEX_WORKER_TOKEN=token, LATEX_API_URL=api_url
                )
                label = hashlib.sha256((api_url + "/" + identity).encode()).hexdigest()[:24]
                processes.append(
                    subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "polycolab.document_builds.worker",
                            "--worker-id",
                            identity,
                            "--state-dir",
                            str(directory / "worker"),
                        ],
                        cwd=ROOT / "src/backend",
                        env=worker_env,
                        stdout=diagnostics,
                        stderr=diagnostics,
                        start_new_session=True,
                    )
                )
                print("Running real LaTeX browser journey", flush=True)
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
                        "latex.spec.ts",
                        "--output",
                        str(directory / "browser"),
                    ],
                    cwd=ROOT,
                    env=env,
                ).returncode
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                for process in processes:
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                if label:
                    reconcile(label)
                subprocess.run(
                    compose + ["down", "--volumes", "--remove-orphans"],
                    stdout=diagnostics,
                    stderr=diagnostics,
                    timeout=60,
                    check=True,
                )


if __name__ == "__main__":
    raise SystemExit(main())

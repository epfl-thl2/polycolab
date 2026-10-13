"""Disposable PostgreSQL/Garage/core/browser gate with a native SSH executor.

Requires POLYCOLAB_GVISOR_SSH_HOST and POLYCOLAB_GVISOR_REMOTE_SOURCE. The remote
source must have locked dependencies, matching code and an idle controller.toml.
Only a deterministic provider transport is substituted; no live provider is used.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    host = os.environ["POLYCOLAB_GVISOR_SSH_HOST"]
    source = os.environ["POLYCOLAB_GVISOR_REMOTE_SOURCE"]
    if host.startswith("-") or not source.startswith("/"):
        raise ValueError("explicit SSH host and absolute disposable source path required")
    remote_port = int(os.environ.get("POLYCOLAB_GVISOR_REMOTE_PORT", "55073"))
    development = os.environ.get("POLYCOLAB_HOSTED_DEV") == "1"
    identity = "hostedtest" + uuid4().hex[:12]
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]
    compose = [
        "docker",
        "compose",
        "-p",
        identity,
        "-f",
        str(ROOT / "tests/system/research-compose.yaml"),
    ]
    children: list[subprocess.Popen[bytes]] = []
    started_remote = False
    with (
        tempfile.TemporaryDirectory(prefix="polycolab-hosted-") as directory,
        tempfile.TemporaryDirectory(
            prefix=".svelte-kit-test-", dir=ROOT / "src/web"
        ) as web_directory,
    ):
        folder = Path(directory)
        log = (folder / "services.log").open("wb")

        def command(args: list[str], **kwargs: Any) -> None:
            child = subprocess.Popen(args, stdout=log, stderr=log, start_new_session=True, **kwargs)
            try:
                status = child.wait(timeout=600)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=15)
                raise
            if status:
                raise subprocess.CalledProcessError(status, args)

        try:
            config = tomllib.loads(
                subprocess.check_output(
                    ssh + ["cat " + shlex.quote(source + "/controller.toml")], text=True
                )
            )
            assert config["backend"] == "gvisor"
            command(compose + ["up", "-d", "--wait"])

            def port(service: str, internal: str) -> str:
                return (
                    subprocess.check_output(compose + ["port", service, internal], text=True)
                    .strip()
                    .rsplit(":", 1)[1]
                )

            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                api_port = reservation.getsockname()[1]
            api_origin = f"http://127.0.0.1:{api_port}"
            web_port = api_port
            if development:
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    web_port = reservation.getsockname()[1]
            origin = f"http://127.0.0.1:{web_port}"
            token = secrets.token_hex(32)
            env = {
                **os.environ,
                "APP_ENV": "local",
                "AUTH_MODE": "local",
                "KMS_PROVIDER": "local",
                "LOCAL_CREDENTIAL_MASTER_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                "BOOTSTRAP_ADMIN_PASSWORD": "Hosted-test-password-2026!",
                "ALLOWED_ORIGINS": json.dumps([origin]),
                "POLYCOLAB_API_PROXY_TARGET": api_origin,
                "POLYCOLAB_SVELTE_OUT_DIR": Path(web_directory).name,
                "DATABASE_URL": (
                    "postgresql+psycopg://research:research-test-only@127.0.0.1:"
                    f"{port('postgres', '5432')}/research"
                ),
                "ARTIFACT_S3_ENDPOINT": f"http://127.0.0.1:{port('garage', '3900')}",
                "ARTIFACT_S3_BUCKET": "research-artifacts",
                "ARTIFACT_S3_REGION": "garage",
                "ARTIFACT_S3_ACCESS_KEY": "GK0123456789abcdef0123456789",
                "ARTIFACT_S3_SECRET_KEY": "0123456789abcdef" * 4,
                "PROJECT_REPOSITORY_DIRECTORY": str(folder / "repositories"),
                "FEATURE_AGENT_EXECUTION_ENABLED": "true",
                "RUNTIME_WORKER_TOKEN": token,
                "RUNTIME_SANDBOX_BACKEND": "gvisor",
                "RUNTIME_SANDBOX_VERSION": config["sandbox_version"],
                "RUNTIME_CODEX_IMAGE": next(
                    image["reference"] for image in config["images"] if image["language"] == "AGENT"
                ),
                "HOSTED_AGENT_CAPACITY": "1",
                "RUNTIME_SSE_POLL_SECONDS": "0.05",
            }
            for module in (["alembic", "upgrade", "head"], ["polycolab.bootstrap_admin"]):
                command([sys.executable, "-m", *module], cwd=ROOT / "src/backend", env=env)
            if not development:
                command(["pnpm", "--filter", "@polycolab/web", "run", "build"], cwd=ROOT)
            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "serve_hosted:app",
                    "--app-dir",
                    str(ROOT / "tests/system"),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--no-access-log",
                ],
                cwd=ROOT / "src/backend",
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            children.append(api)
            with httpx.Client(base_url=api_origin, trust_env=False) as client:
                for _ in range(600):
                    if api.poll() is not None:
                        raise RuntimeError("core_start_failed")
                    try:
                        if client.get("/health/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("core_readiness_timeout")
            if development:
                web = subprocess.Popen(
                    [
                        "node",
                        "node_modules/vite/bin/vite.js",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(web_port),
                        "--strictPort",
                    ],
                    cwd=ROOT / "src/web",
                    env=env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                children.append(web)
                for _ in range(150):
                    if web.poll() is not None:
                        raise RuntimeError("web_start_failed")
                    try:
                        if httpx.get(origin, timeout=5, trust_env=False).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError("web_readiness_timeout")
            remote_script = source + "/remote_hosted.py"
            command(
                ["scp", str(ROOT / "tests/system/remote_hosted.py"), host + ":" + remote_script]
            )
            remote = subprocess.Popen(
                [
                    *ssh[:-1],
                    "-o",
                    "ExitOnForwardFailure=yes",
                    "-R",
                    f"127.0.0.1:{remote_port}:127.0.0.1:{api_port}",
                    host,
                    shlex.join(
                        [
                            source + "/src/backend/.venv/bin/python",
                            remote_script,
                            source,
                            identity,
                            str(remote_port),
                        ]
                    ),
                ],
                stdin=subprocess.PIPE,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            children.append(remote)
            started_remote = True
            assert remote.stdin is not None
            remote.stdin.write((token + "\n").encode())
            remote.stdin.close()
            command(
                [
                    "pnpm",
                    "--filter",
                    "@polycolab/web",
                    "exec",
                    "playwright",
                    "test",
                    "--config",
                    "../../tests/system/playwright.config.ts",
                    "hosted-gvisor-real-service.spec.ts",
                    "--trace",
                    "off",
                    "--output",
                    str(folder / "browser"),
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "POLYCOLAB_GVISOR_BROWSER": "1",
                    "POLYCOLAB_INTEGRATION_WEB_URL": origin,
                },
            )
            print(
                "PASS: native Docker/gVisor chat and reload against PostgreSQL/Garage/core"
                + (" (Vite frontend)" if development else " (compiled frontend)")
            )
            return 0
        except Exception:
            # Synthetic fixtures only. Retain private diagnostics for local investigation.
            log.flush()
            failure = Path(tempfile.mkdtemp(prefix="polycolab-hosted-failure-"))
            (failure / "services.log").write_bytes((folder / "services.log").read_bytes())
            if (folder / "browser").exists():
                shutil.copytree(folder / "browser", failure / "browser")
            print(f"Hosted gate failed; private diagnostics: {failure}", file=sys.stderr)
            raise
        finally:
            if started_remote:
                stop = (
                    "import os,signal; from pathlib import Path; "
                    f"p=Path({(source + '/' + identity + '.pid')!r}); "
                    "pid=int(p.read_text()) if p.exists() else 0; "
                    f"expected={identity!r}.encode(); "
                    "args=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\\0') if pid else []; "
                    "os.kill(pid,signal.SIGTERM) if pid and expected in args else None"
                )
                subprocess.run(
                    ssh + [shlex.join(["python3", "-c", stop])], stdout=log, stderr=log, timeout=30
                )
            for child in reversed(children):
                try:
                    child.wait(timeout=30 if child is children[-1] and started_remote else 1)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
            subprocess.run(
                compose + ["down", "--volumes", "--remove-orphans"],
                stdout=log,
                stderr=log,
                timeout=120,
            )
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())

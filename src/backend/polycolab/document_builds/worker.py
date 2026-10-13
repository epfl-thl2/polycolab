"""Host controller for one isolated LaTeX slot; only private HTTP and Docker.

Run multiple processes with distinct worker IDs for additional capacity. No
application settings, database modules, or provider credentials are loaded here.
"""

import argparse
import fcntl
import hashlib
import json
import logging
import math
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LatexWorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[4] / "deploy/docker/.env", extra="ignore"
    )
    latex_worker_token: SecretStr | None = None
    latex_image: str | None = None
    latex_api_url: str = "http://127.0.0.1:8000"


logger = logging.getLogger(__name__)
MAX_OUTPUT = 17 * 1024 * 1024 + 4096
IMAGE_PATTERN = r"(?:[a-zA-Z0-9][a-zA-Z0-9./_:-]*@)?sha256:[a-f0-9]{64}"


def docker(*args: str, timeout: float = 30) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, timeout=timeout, check=True)
    return result.stdout.decode().strip()


def container_command(
    image: str, name: str, label: str, engine: str, main: str, seconds: int
) -> list[str]:
    return [
        "create",
        "--name",
        name,
        "--label",
        f"polycolab.latex.worker={label}",
        "--pull=never",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--cap-add=SETUID",
        "--cap-add=SETGID",
        "--cap-add=KILL",
        "--security-opt=no-new-privileges",
        "--cpus=1",
        "--memory=1g",
        "--memory-swap=1g",
        "--pids-limit=128",
        "--ulimit",
        "core=0",
        "--tmpfs",
        "/work:rw,nosuid,nodev,noexec,size=256m,mode=1777",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m,mode=1777",
        # The bundled Biber interpreter extracts native libraries/executables.
        "--tmpfs",
        "/biber:rw,nosuid,nodev,exec,size=128m,mode=1777",
        "--log-driver=none",
        "--interactive",
        image,
        engine,
        main,
        str(seconds),
    ]


def preflight(image: str) -> None:
    if not re.fullmatch(IMAGE_PATTERN, image):
        raise ValueError("LATEX_IMAGE must be an immutable image ID or repository digest")
    info = json.loads(docker("info", "--format", "{{json .}}"))
    if info.get("OSType") != "linux" or str(info.get("CgroupVersion")) != "2":
        raise ValueError("Docker must provide Linux containers and cgroup v2")
    if (
        any("rootless" in option for option in info.get("SecurityOptions", []))
        and info.get("CgroupDriver") != "systemd"
    ):
        raise ValueError("Rootless Docker requires the systemd cgroup driver")
    if not all(info.get(key) for key in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit")):
        raise ValueError("Docker must enforce memory, swap, CPU, and process limits")
    docker("image", "inspect", image)


def reconcile(label: str) -> None:
    ids = docker("ps", "-aq", "--filter", f"label=polycolab.latex.worker={label}")
    for identifier in ids.splitlines():
        docker("rm", "--force", identifier)


def bounded_get(client: httpx.Client, path: str, maximum: int, **kwargs: Any) -> bytes:
    result = bytearray()
    with client.stream("GET", path, **kwargs) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            result.extend(chunk)
            if len(result) > maximum:
                raise ValueError("Build transfer limit exceeded")
    return bytes(result)


def execute(client: httpx.Client, claim: dict[str, Any], label: str) -> None:
    identifier, generation = claim["id"], claim["generation"]
    route = f"/internal/latex/{identifier}"
    deadline = datetime.fromisoformat(claim["deadline"].replace("Z", "+00:00"))
    source = bounded_get(
        client, route + "/input", 16 * 1024 * 1024, params={"generation": generation}
    )
    if hashlib.sha256(source).hexdigest() != claim["input_sha256"]:
        raise ValueError("Build input digest mismatch")
    seconds = math.floor((deadline - datetime.now(UTC)).total_seconds()) - 5
    if seconds < 1:
        raise ValueError("Build deadline elapsed")
    name = "polycolab-latex-" + identifier
    created = False
    process: subprocess.Popen[bytes] | None = None
    stopped = False
    status, error = "failed", "latex_worker_error"
    log, pdf = b"", b""
    try:
        # The label precedes execution, allowing recovery even after ambiguous creation.
        docker(
            *container_command(
                claim["image"], name, label, claim["engine"], claim["main_file"], seconds
            )
        )
        created = True
        with (
            tempfile.TemporaryFile() as stdin,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            stdin.write(source)
            stdin.seek(0)
            process = subprocess.Popen(
                ["docker", "start", "--attach", "--interactive", name],
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
            )
            last_heartbeat = 0.0
            while process.poll() is None:
                if stdout.tell() > MAX_OUTPUT or stderr.tell() > 65536:
                    raise ValueError("Build output limit exceeded")
                if datetime.now(UTC) >= deadline:
                    status, error = "timed_out", "latex_timeout"
                    break
                if time.monotonic() - last_heartbeat >= 5:
                    client.post(
                        route + "/heartbeat", json={"generation": generation}
                    ).raise_for_status()
                    last_heartbeat = time.monotonic()
                time.sleep(0.1)
            if process.poll() is not None and process.returncode == 0:
                stdout.seek(0)
                raw = stdout.read(MAX_OUTPUT + 1)
                header, payload = raw.split(b"\n", 1)
                if len(header) > 4096 or len(raw) > MAX_OUTPUT:
                    raise ValueError("Invalid build output")
                value = json.loads(header)
                nlog, npdf = value["log_bytes"], value["pdf_bytes"]
                if not (
                    0 <= nlog <= 1024 * 1024
                    and 0 <= npdf <= 16 * 1024 * 1024
                    and len(payload) == nlog + npdf
                ):
                    raise ValueError("Invalid build output lengths")
                status, error = value["status"], value["error"]
                log, pdf = payload[:nlog], payload[nlog:]
    finally:
        # Always reconcile by deterministic name, including ambiguous create errors.
        try:
            docker("rm", "--force", name)
            stopped = True
        except subprocess.CalledProcessError:
            if not created and not docker("ps", "-aq", "--filter", f"name=^/{name}$"):
                stopped = True
        if process is not None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if not stopped:
            raise RuntimeError("Container cleanup unconfirmed")
        # A cancellation/lease loss may reject completion; release is still safe
        # only after Docker has confirmed the container no longer exists.
        try:
            if log:
                client.put(
                    route + "/outputs/log", params={"generation": generation}, content=log
                ).raise_for_status()
            if pdf and status == "succeeded":
                client.put(
                    route + "/outputs/pdf", params={"generation": generation}, content=pdf
                ).raise_for_status()
            client.post(
                route + "/complete",
                json={"generation": generation, "status": status, "error": error},
            ).raise_for_status()
        finally:
            client.post(route + "/release", json={"generation": generation}).raise_for_status()


def main() -> None:
    settings = LatexWorkerSettings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=settings.latex_api_url)
    parser.add_argument("--image", default=settings.latex_image)
    parser.add_argument("--worker-id", default="latex-local")
    parser.add_argument("--state-dir", type=Path, default=Path(".local/latex-worker"))
    args = parser.parse_args()
    token = settings.latex_worker_token.get_secret_value() if settings.latex_worker_token else None
    if not token or not args.image:
        parser.error("LATEX_WORKER_TOKEN and LATEX_IMAGE are required")
    url = urlparse(args.api)
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        parser.error("The API must use HTTPS or loopback HTTP")
    if url.username or url.password or url.query or url.fragment:
        parser.error("Invalid API URL")
    label = hashlib.sha256((args.api + "/" + args.worker_id).encode()).hexdigest()[:24]
    args.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO)
    with (args.state_dir / (label + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        preflight(args.image)
        reconcile(label)
        with httpx.Client(
            base_url=args.api,
            headers={"Authorization": "Bearer " + token},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            while True:
                try:
                    # Reconciliation before readiness prevents reuse after uncertain cleanup.
                    reconcile(label)
                    client.post(
                        "/internal/latex/ready", json={"image": args.image}
                    ).raise_for_status()
                    response = client.post(
                        "/internal/latex/claim", json={"worker_id": args.worker_id}
                    )
                    response.raise_for_status()
                    claim = response.json()
                    if claim:
                        if claim["image"] != args.image:
                            raise ValueError("Build image mismatch")
                        execute(client, claim, label)
                except (
                    httpx.HTTPError,
                    ValueError,
                    OSError,
                    subprocess.SubprocessError,
                    RuntimeError,
                ):
                    logger.warning(
                        "LaTeX attempt or transport failed; reconciling before next claim"
                    )
                time.sleep(2)


if __name__ == "__main__":
    main()

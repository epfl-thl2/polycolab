"""Administrator-owned, standard-library-only Docker containment helper.

Install a root-owned wrapper that supplies a fixed root-owned configuration.
The controller supplies only an action and an attempt UUID, never a command.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_json(path: Path, uid: int) -> dict[str, Any]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != uid
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or info.st_size > 16384
        ):
            raise ValueError("invalid host configuration")
        value = json.loads(os.read(fd, 16385))
        if not isinstance(value, dict):
            raise ValueError("invalid host configuration")
        return value
    finally:
        os.close(fd)


def command(*args: str, timeout: float = 10, missing: bool = False) -> bytes:
    result = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"},
        check=False,
    )
    if (result.returncode and not missing) or len(result.stdout) > 65536:
        raise RuntimeError("host operation failed")
    return result.stdout


class Host:
    def __init__(self, config: Path) -> None:
        self.config_path = config.resolve()
        self.config = read_json(self.config_path, 0)
        self.root = Path(self.config["state_dir"])
        self.uid = int(self.config["executor_uid"])
        self.socket = self.config["docker_socket"]
        if not self.root.is_absolute() or not self.socket.startswith("/"):
            raise ValueError("invalid host paths")

    def check_state(self) -> None:
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.uid or info.st_mode & 0o077:
            raise ValueError("private controller state required")

    def docker(self, *args: str) -> bytes:
        return command("docker", "--host", "unix://" + self.socket, *args)

    def names(self, attempt: str) -> tuple[str, str, str]:
        if not re.fullmatch(r"[0-9a-f]{32}", attempt):
            raise ValueError("invalid attempt")
        return (
            f"polycolabexec-{attempt}.slice",
            f"polycolab-guard-{attempt}.service",
            f"polycolab-holder-{attempt}.service",
        )

    def record(self, attempt: str) -> dict[str, Any]:
        self.names(attempt)
        self.check_state()
        value = read_json(self.root / "attempts" / (attempt + ".json"), self.uid)
        if (
            value.get("backend") != "gvisor"
            or value.get("container") != "polycolab-exec-" + attempt
        ):
            raise ValueError("invalid attempt journal")
        return value

    def group(self, attempt: str) -> Path:
        name, _, _ = self.names(attempt)
        # systemd expands the slice hierarchy according to hyphens.
        return Path("/sys/fs/cgroup/polycolabexec.slice") / name

    def check(self) -> None:
        self.check_state()
        if os.geteuid() != 0 or not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise ValueError("root cgroup v2 helper required")
        binary = Path(self.config["runsc_path"])
        if binary.stat().st_uid != 0 or binary.stat().st_mode & 0o022:
            raise ValueError("runtime must be administrator owned")
        if hashlib.sha256(binary.read_bytes()).hexdigest() != self.config["runsc_sha256"]:
            raise ValueError("runtime digest mismatch")
        if self.config["runsc_version"] not in command(str(binary), "--version").decode().split():
            raise ValueError("runtime version mismatch")
        info = json.loads(self.docker("info", "--format", "{{json .}}"))
        runtime = info["Runtimes"][self.config["runtime_name"]]
        if (
            info["CgroupVersion"] != "2"
            or info["CgroupDriver"] != "systemd"
            or runtime["path"] != str(binary)
            or "--platform=systrap" not in runtime.get("runtimeArgs", [])
            or "--network=none" not in runtime.get("runtimeArgs", [])
        ):
            raise ValueError("daemon runtime configuration mismatch")

    def prepare(self, attempt: str) -> None:
        self.check()
        row = self.record(attempt)
        limits = row["limits"]
        remaining = (datetime.fromisoformat(row["deadline"]) - datetime.now(UTC)).total_seconds()
        if not 0 < remaining <= 3600:
            raise ValueError("expired attempt")
        memory, tasks, cpus = (
            int(limits["memory_bytes"]),
            int(limits["process_count"]),
            int(limits["cpu_count"]),
        )
        if not (16 * 1024**2 <= memory <= 16 * 1024**3 and 1 <= tasks <= 256 and 1 <= cpus <= 8):
            raise ValueError("invalid limits")
        cpu_seconds = int(limits["cpu_seconds"])
        if not 1 <= cpu_seconds <= 28800:
            raise ValueError("invalid cpu budget")
        cpu_quota = int(min(cpus, cpu_seconds / remaining) * 100)
        if cpu_quota < 1:
            raise ValueError("cpu budget below host quota precision")
        slice_name, guard, holder = self.names(attempt)
        stop = f"/usr/bin/python3 {Path(__file__).resolve()} {self.config_path} stop {attempt}"
        # The guard is outside the workload slice; its stop hook can kill the whole slice.
        command(
            "systemd-run",
            "--quiet",
            "--unit=" + guard,
            "--property=RuntimeMaxSec=" + str(remaining),
            "--property=TimeoutStopSec=15",
            "--property=ExecStopPost=" + stop,
            "/usr/bin/sleep",
            "infinity",
        )
        command(
            "systemd-run",
            "--quiet",
            "--unit=" + holder,
            "--slice=" + slice_name,
            "--property=BindsTo=" + guard,
            "--property=After=" + guard,
            "/usr/bin/sleep",
            "infinity",
        )
        command(
            "systemctl",
            "set-property",
            "--runtime",
            slice_name,
            f"MemoryMax={memory + 512 * 1024**2}",
            "MemorySwapMax=0",
            "TasksMax=256",
            f"CPUQuota={cpu_quota}%",
        )

    def verify(self, attempt: str) -> None:
        row = self.record(attempt)
        group = self.group(attempt)
        info = json.loads(self.docker("inspect", row["container"]))[0]
        if (
            not info["State"]["Running"]
            or info["HostConfig"]["Runtime"] != self.config["runtime_name"]
        ):
            raise ValueError("sandbox not running")
        relative = str(group.relative_to("/sys/fs/cgroup"))
        pid = int(info["State"]["Pid"])
        membership = Path(f"/proc/{pid}/cgroup").read_text()
        if "0::/" + relative + "/" not in membership:
            raise ValueError("sandbox outside containment")
        # Include Gofer and Sentry, not merely Docker's reported init PID.
        for proc in Path("/proc").iterdir():
            if not proc.name.isdecimal():
                continue
            try:
                args = (proc / "cmdline").read_bytes().split(b"\0")
                if info["Id"].encode() in args and any(b"runsc" in arg for arg in args[:1]):
                    if "0::/" + relative + "/" not in (proc / "cgroup").read_text():
                        raise ValueError("runtime helper outside containment")
            except FileNotFoundError, ProcessLookupError:
                continue
        for item in ("memory.max", "pids.max"):
            if not (group / item).read_text().strip().isdecimal():
                raise ValueError("unbounded sandbox")
        if (group / "cpu.max").read_text().split()[0] == "max":
            raise ValueError("unbounded cpu")
        if (datetime.fromisoformat(row["deadline"]) - datetime.now(UTC)).total_seconds() <= 0:
            raise ValueError("expired attempt")

    def stop(self, attempt: str) -> None:
        group = self.group(attempt)
        # The guard must work without Docker or controller-owned journal storage.
        # Only the validated UUID selects a cgroup in the fixed executor namespace.
        kill = group / "cgroup.kill"
        if kill.exists():
            kill.write_text("1")
        slice_name, _, holder = self.names(attempt)
        command("systemctl", "stop", holder, slice_name, missing=True)
        events = group / "cgroup.events"
        if events.exists() and "populated 1" in events.read_text():
            raise ValueError("sandbox termination unconfirmed")

    def release(self, attempt: str) -> None:
        self.stop(attempt)
        _, guard, holder = self.names(attempt)
        command("systemctl", "stop", guard, missing=True)
        command("systemctl", "reset-failed", guard, holder, missing=True)


def main() -> int:
    try:
        if len(sys.argv) not in (3, 4):
            raise ValueError("invalid arguments")
        host = Host(Path(sys.argv[1]))
        action = sys.argv[2]
        if action == "check" and len(sys.argv) == 3:
            host.check()
            print(
                json.dumps(
                    {k: host.config[k] for k in ("runsc_version", "runtime_name", "docker_socket")}
                )
            )
        elif action in {"prepare", "verify", "stop", "release"} and len(sys.argv) == 4:
            getattr(host, action)(sys.argv[3])
        else:
            raise ValueError("invalid action")
    except Exception:
        print("execution containment check failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Credential-free container entrypoint; root supervises an unprivileged compiler.

This file is copied into a read-only image. It must never import project code.
The controller provides a bounded ZIP on stdin and receives framed output bytes.
"""

import io
import json
import os
import resource
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath

MAX_INPUT = 16 * 1024 * 1024
MAX_LOG = 1024 * 1024
MAX_PDF = 16 * 1024 * 1024
UID = 65534


def safe_path(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        bool(name)
        and not path.is_absolute()
        and all(part not in {"", ".", "..", ".git"} for part in name.split("/"))
        and "\\" not in name
        and not any(ord(c) < 32 for c in name)
    )


def child(engine: str, main_file: str) -> int:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PDF, MAX_PDF))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    root = Path("/work/source")
    root.mkdir()
    output = Path("/work/output")
    output.mkdir()
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT or not safe_path(main_file):
        raise ValueError("Invalid source")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 4096 or sum(item.file_size for item in infos) > MAX_INPUT:
            raise ValueError("Source limit")
        names = set()
        for item in infos:
            mode = item.external_attr >> 16
            if (
                not safe_path(item.filename)
                or item.filename in names
                or stat.S_ISLNK(mode)
                or item.is_dir()
            ):
                raise ValueError("Invalid source entry")
            names.add(item.filename)
            target = root / item.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(archive.read(item))
    if main_file not in names or engine not in {"pdflatex", "lualatex"}:
        raise ValueError("Invalid main file or engine")
    env = {
        "PATH": "/opt/texlive/bin/current:/usr/local/bin:/usr/bin:/bin",
        "HOME": "/work",
        "TMPDIR": "/tmp",
        "LANG": "C.UTF-8",
        "TEXMFVAR": "/work/texmf-var",
        "TEXMFCONFIG": "/work/texmf-config",
        "shell_escape": "f",
        "openin_any": "a",
        "PAR_GLOBAL_TEMP": "/biber/cache",
        "openout_any": "p",
        "SOURCE_DATE_EPOCH": "0",
        "FORCE_SOURCE_DATE": "1",
    }
    command = [
        "latexmk",
        "-norc",
        "-pdf" if engine == "pdflatex" else "-lualatex",
        "-interaction=nonstopmode",
        "-file-line-error",
        "-halt-on-error",
        "-no-shell-escape",
        "-jobname=document",
        "-outdir=/work/output",
        "./" + main_file,
    ]
    with Path("/work/build.log").open("wb") as log:
        return subprocess.run(
            command,
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        ).returncode


def stop_compilers() -> None:
    # Descendants can create new process groups. Kill every compiler UID in this
    # private PID namespace, not just the original latexmk process group.
    for _ in range(10):
        live = []
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    if entry.stat().st_uid == UID:
                        state = (entry / "stat").read_text().split(") ", 1)[1][0]
                        if state != "Z":
                            live.append(int(entry.name))
                except (OSError, IndexError):
                    pass
        if not live:
            return
        for pid in live:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(0.01)
    raise RuntimeError("Compiler cleanup failed")


def regular_file(path: Path, limit: int, truncate: bool = False) -> bytes:
    # Parent directories must also be real directories controlled by this build.
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("Invalid output path")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return b""
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Invalid output type")
        if info.st_size > limit and not truncate:
            raise ValueError("Output limit")
        data = handle.read(limit)
        if truncate and info.st_size > limit:
            suffix = b"\n[Log truncated]\n"
            data = data[: limit - len(suffix)] + suffix
        return data


def supervise(engine: str, main_file: str, seconds: int) -> None:
    if os.getuid() != 0 or not 1 <= seconds <= 300:
        raise ValueError("Invalid supervisor configuration")
    data = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("Input limit")
    # The root supervisor has a different UID so TeX cannot signal its watchdog.
    process = subprocess.Popen(
        [sys.executable, "-I", __file__, "--child", engine, main_file],
        user=UID,
        group=UID,
        extra_groups=[],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    status, error = "failed", "latex_compile_failed"
    try:
        process.communicate(data, timeout=seconds)
        if process.returncode == 0:
            status, error = "succeeded", None
    except subprocess.TimeoutExpired:
        status, error = "timed_out", "latex_timeout"
    finally:
        stop_compilers()
        process.wait(timeout=5)
    log = regular_file(Path("/work/build.log"), MAX_LOG, truncate=True)
    pdf = b""
    try:
        if status == "succeeded":
            pdf = regular_file(Path("/work/output/document.pdf"), MAX_PDF)
            if not pdf.startswith(b"%PDF-"):
                status, error, pdf = "failed", "latex_compile_failed", b""
    except (OSError, ValueError):
        status, error = "failed", "latex_output_limit"
    header = json.dumps(
        {"status": status, "error": error, "log_bytes": len(log), "pdf_bytes": len(pdf)}
    ).encode()
    sys.stdout.buffer.write(header + b"\n" + log + pdf)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    if sys.argv[1] == "--child":
        sys.exit(child(sys.argv[2], sys.argv[3]))
    supervise(sys.argv[1], sys.argv[2], int(sys.argv[3]))

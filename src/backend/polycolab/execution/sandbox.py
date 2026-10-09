"""Sandbox boundary and bounded collection, not a production process launcher.

Only a separately accepted isolation adapter may execute SandboxRuntime jobs.
There is deliberately no subprocess, Docker/runc or host-Python fallback.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from polycolab.verification.contracts import ControllerClaim, ResourceLimits, validate_path


class SandboxUnavailable(Exception):
    pass


class UnsafeSandboxOutput(Exception):
    pass


@dataclass(frozen=True)
class SandboxOutput:
    path: str
    role: Literal["OUTPUT", "CERTIFICATE", "DIAGNOSTIC"]
    data: bytes


@dataclass(frozen=True)
class SandboxResult:
    outcome: Literal["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]
    exit_code: int | None
    diagnostic_code: Literal[
        "NONE", "PROGRAM_ERROR", "RESOURCE_LIMIT", "CANCELLED", "LEASE_LOST", "RUNTIME_UNAVAILABLE"
    ]
    outputs: tuple[SandboxOutput, ...] = ()


class SandboxRuntime(Protocol):
    async def check_ready(self) -> None:
        """Reject unavailable/unaccepted isolation before any job claim."""
        ...

    async def reconcile(self) -> None:
        """Stop only this controller's orphan sandboxes before claiming work."""
        ...

    async def run(self, claim: ControllerClaim, inputs: dict[str, bytes]) -> SandboxResult:
        """Enforce the absolute execution deadline and all admitted ceilings.

        Cancellation must synchronously stop the sandbox before this await exits.
        Never return paths to a still-running or writable sandbox filesystem.
        """
        ...


def collect_outputs(
    root: Path, limits: ResourceLimits, selected: set[str] | None = None
) -> tuple[SandboxOutput, ...]:
    """Read a stopped sandbox's private output directory without following links.

    Directory/file descriptors prevent path substitution. Hard links, symlinks,
    special files, changing files, overlarge trees and budgets fail closed. The
    caller must first stop every sandbox process; this is not a live-file viewer.
    """
    outputs: list[SandboxOutput] = []
    total = output_bytes = log_bytes = visited = 0
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW

    def walk(directory: int, prefix: str, depth: int) -> None:
        nonlocal total, output_bytes, log_bytes, visited
        if depth > 16:
            raise UnsafeSandboxOutput("output_tree_too_deep")
        if selected is None:
            from itertools import islice

            with os.scandir(directory) as entries:
                names = [entry.name for entry in islice(entries, 4097)]
        else:
            names = sorted(
                {path[len(prefix) :].split("/")[0] for path in selected if path.startswith(prefix)}
            )
        for name in names:
            visited += 1
            if visited > 4096:
                raise UnsafeSandboxOutput("output_tree_too_large")
            path = prefix + name
            if (
                len(path) > 240
                or not path.isascii()
                or any(
                    c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_./-"
                    for c in path
                )
            ):
                raise UnsafeSandboxOutput("invalid_output_path")
            validate_path(path)
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if stat.S_ISDIR(before.st_mode):
                child = os.open(name, flags | os.O_DIRECTORY, dir_fd=directory)
                try:
                    walk(child, path + "/", depth + 1)
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise UnsafeSandboxOutput("output_must_be_unlinked_regular_file")
            diagnostic = selected is None and path in {"stdout.log", "stderr.log"}
            available = (
                (limits.log_bytes - log_bytes)
                if diagnostic
                else (limits.output_bytes - output_bytes)
            )
            if (
                len(outputs) >= limits.output_files
                or before.st_size > available
                or total + before.st_size > 16 * 1024 * 1024
            ):
                raise UnsafeSandboxOutput("output_budget_exceeded")
            fd = os.open(name, flags | os.O_NONBLOCK, dir_fd=directory)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) != (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    1,
                ) or not stat.S_ISREG(opened.st_mode):
                    raise UnsafeSandboxOutput("output_changed")
                data = bytearray()
                while chunk := os.read(fd, min(65536, before.st_size - len(data) + 1)):
                    if len(data) + len(chunk) > before.st_size:
                        raise UnsafeSandboxOutput("output_changed")
                    data.extend(chunk)
                after = os.fstat(fd)
                if (
                    len(data) != before.st_size
                    or after.st_mtime_ns != before.st_mtime_ns
                    or after.st_nlink != 1
                ):
                    raise UnsafeSandboxOutput("output_changed")
            finally:
                os.close(fd)
            total += len(data)
            if diagnostic:
                log_bytes += len(data)
            else:
                output_bytes += len(data)
            outputs.append(
                SandboxOutput(path, "DIAGNOSTIC" if diagnostic else "OUTPUT", bytes(data))
            )

    try:
        directory = os.open(root, flags | os.O_DIRECTORY)
        try:
            walk(directory, "", 0)
        finally:
            os.close(directory)
    except OSError, ValueError:
        raise UnsafeSandboxOutput("unsafe_output_tree") from None
    return tuple(sorted(outputs, key=lambda item: item.path))

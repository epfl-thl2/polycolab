"""Git project helpers inside the untrusted guest; never hold service credentials."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def git(directory: Path, *arguments: str) -> str:
    env = {
        "PATH": os.defpath,
        "HOME": "/tmp",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Project agent",
        "GIT_AUTHOR_EMAIL": "agent@polycolab.invalid",
        "GIT_COMMITTER_NAME": "Polycolab",
        "GIT_COMMITTER_EMAIL": "project@polycolab.invalid",
    }
    return (
        subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.file.allow=always",
                *arguments,
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
        )
        .stdout.decode()
        .strip()
    )


def checkout(
    inputs: Path = Path("/inputs"), project: Path = Path("/workspace")
) -> dict[str, str] | None:
    metadata = inputs / "workspace.json"
    if not metadata.exists():
        return None
    value: dict[str, str] = json.loads(metadata.read_text())
    branch, commit = value["branch"], value["commit"]
    git(inputs, "clone", "--no-local", str(inputs / "workspace.bundle"), str(project))
    git(
        project,
        "fetch",
        "--no-tags",
        str(inputs / "workspace.bundle"),
        "refs/polycolab-checkout/input",
    )
    git(project, "checkout", "-B", branch, commit)
    git(project, "config", "user.name", "Project agent")
    git(project, "config", "user.email", "agent@polycolab.invalid")
    if git(project, "rev-parse", "HEAD") != commit:
        raise ValueError("repository_input_mismatch")
    if value.get("revision"):
        # Restore the saved overlay while keeping HEAD and the index at the human commit.
        git(project, "read-tree", "--reset", "-u", value["revision"])
        git(project, "reset", "--mixed", commit)
    return value


def checkpoint(
    value: dict[str, str], project: Path = Path("/workspace"), output: Path = Path("/outputs")
) -> str:
    branch = value["branch"]
    if git(project, "symbolic-ref", "--short", "HEAD") != branch:
        raise ValueError("repository_branch_changed")
    git(project, "merge-base", "--is-ancestor", value["commit"], "HEAD")
    git(project, "add", "-A", "--", ".")
    if git(project, "status", "--porcelain"):
        git(project, "commit", "-m", "Save agent project files")
    git(project, "bundle", "create", str(output / "workspace.bundle"), f"refs/heads/{branch}")
    return git(project, "rev-parse", "HEAD")


def require_idle(codex_pid: int) -> None:
    # Background children also make a refresh unsafe, even after a tool reports completion.
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) in {os.getpid(), codex_pid}:
            continue
        try:
            if entry.stat().st_uid == os.getuid():
                raise ValueError("workspace_processes_active")
        except FileNotFoundError:
            continue


def refresh(
    value: dict[str, str], bundle: bytes, base: str, commit: str, project: Path = Path("/workspace")
) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(dir="/tmp") as stream:
        stream.write(bundle)
        stream.flush()
        git(project, "fetch", "--no-tags", stream.name, "refs/polycolab-checkout/input")
    git(project, "merge-base", "--is-ancestor", base, commit)
    git(project, "checkout", "-B", value["branch"], commit)
    if git(project, "rev-parse", "HEAD") != commit:
        raise ValueError("workspace_refresh_mismatch")
    value["commit"] = base

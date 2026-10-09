"""Git workspace helpers inside the untrusted guest; never hold service credentials."""

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
        "GIT_AUTHOR_NAME": "Workspace agent",
        "GIT_AUTHOR_EMAIL": "agent@polycolab.invalid",
        "GIT_COMMITTER_NAME": "Polycolab",
        "GIT_COMMITTER_EMAIL": "workspace@polycolab.invalid",
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
    inputs: Path = Path("/inputs"), workspace: Path = Path("/workspace")
) -> dict[str, str] | None:
    metadata = inputs / "workspace.json"
    if not metadata.exists():
        return None
    value: dict[str, str] = json.loads(metadata.read_text())
    branch, commit = value["branch"], value["commit"]
    git(inputs, "clone", "--no-local", str(inputs / "workspace.bundle"), str(workspace))
    git(
        workspace,
        "fetch",
        "--no-tags",
        str(inputs / "workspace.bundle"),
        "refs/polycolab-checkout/input",
    )
    git(workspace, "checkout", "-B", branch, commit)
    git(workspace, "config", "user.name", "Workspace agent")
    git(workspace, "config", "user.email", "agent@polycolab.invalid")
    if git(workspace, "rev-parse", "HEAD") != commit:
        raise ValueError("repository_input_mismatch")
    return value


def checkpoint(
    value: dict[str, str], workspace: Path = Path("/workspace"), output: Path = Path("/outputs")
) -> str:
    branch = value["branch"]
    if git(workspace, "symbolic-ref", "--short", "HEAD") != branch:
        raise ValueError("repository_branch_changed")
    git(workspace, "merge-base", "--is-ancestor", value["commit"], "HEAD")
    git(workspace, "add", "-A", "--", ".")
    if git(workspace, "status", "--porcelain"):
        git(workspace, "commit", "-m", "Save agent workspace files")
    git(workspace, "bundle", "create", str(output / "workspace.bundle"), f"refs/heads/{branch}")
    return git(workspace, "rev-parse", "HEAD")

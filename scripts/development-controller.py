"""Adapt a prepared execution host to the local development launcher's API."""

import argparse
import asyncio
import json
import os
import sqlite3
import tempfile
import tomllib
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["describe", "run", "health"])
    parser.add_argument("config", type=Path)
    parser.add_argument("--api-url")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--previous-incarnation", default="")
    args = parser.parse_args()
    with args.config.open("rb") as stream:
        source = tomllib.load(stream)
    if args.action == "health":
        with sqlite3.connect(f"file:{args.database}?mode=ro", uri=True) as db:
            row = db.execute(
                "SELECT expires_at, capacity, incarnation FROM hosted_executors "
                "WHERE worker_id = ? AND image_digest = ? AND protocol_version = 7 "
                "AND sandbox_backend = ? AND sandbox_version = ?",
                (
                    source.get("worker_id", "codex-controller"),
                    next(
                        i["reference"] for i in source["images"] if i["language"] == "AGENT"
                    ).rsplit("@sha256:", 1)[-1],
                    source.get("backend", "microsandbox"),
                    source.get("sandbox_version", "0.6.18"),
                ),
            ).fetchone()
        healthy = bool(
            row
            and datetime.fromisoformat(row[0]).replace(tzinfo=UTC) > datetime.now(UTC)
            and row[1] > 0
            and row[2] != args.previous_incarnation
        )
        print(json.dumps({"healthy": healthy, "detail": "waiting for controller readiness"}))
        return

    from polycolab.execution.service import ServiceConfig, run

    config = ServiceConfig.model_validate(source)
    if args.action == "describe":
        images = [image for image in config.images if image.language == "AGENT"]
        if len(images) != 1:
            raise ValueError("Exactly one Codex image is required")
        previous = ""
        if args.database and args.database.exists():
            with sqlite3.connect(f"file:{args.database}?mode=ro", uri=True) as db:
                row = db.execute(
                    "SELECT incarnation FROM hosted_executors WHERE worker_id = ?",
                    (config.worker_id,),
                ).fetchone()
                if row:
                    previous = row[0]
        print(
            json.dumps(
                {
                    "image": images[0].reference,
                    "backend": config.backend,
                    "version": config.sandbox_version,
                    "previous": previous,
                }
            )
        )
        return

    from polycolab.platform.config import WorkerSettings

    # A private temporary file avoids putting the shared API token in process arguments.
    fd, credential = tempfile.mkstemp(prefix="polycolab-local-controller-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(WorkerSettings().runtime_worker_secret)
        config = config.model_copy(
            update={
                "api_url": args.api_url,
                "agent_credential_file": credential,
            }
        )
        asyncio.run(run(config))
    finally:
        Path(credential).unlink(missing_ok=True)


if __name__ == "__main__":
    main()

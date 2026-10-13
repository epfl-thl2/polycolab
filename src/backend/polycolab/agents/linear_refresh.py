"""Two-phase refresh of an isolated turn; preparation never changes shared files."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from polycolab.agents.linear_files import content, contribution, reconcile
from polycolab.db.models.linear import SqlLinearRun
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.linear_factory import service
from polycolab.projects.linear_service import decode, encode


def status(settings: Settings, db: Session, run: Any) -> dict[str, Any]:
    instance = service(settings, db, run.project_id, run.requested_by_user_id)
    state = instance.state()
    binding = db.get(SqlLinearRun, run.id)
    if binding is None:
        raise RepositoryError("linear_run_not_found", 404)
    checkpoint = instance.tx.linear.checkpoint(run.project_id, binding.current_checkpoint_id)
    assert checkpoint is not None
    operations = instance.tx.linear.operations(run.project_id, checkpoint.sequence)
    return {
        "input_sequence": checkpoint.sequence,
        "sequence": state.sequence,
        "epoch": state.epoch,
        "restored": state.epoch != binding.epoch,
        "changed_paths": sorted(
            {file["path"] for op in operations for file in op.payload["files"]}
        ),
        "more_changes": len(operations) == 100,
    }


def prepare(
    settings: Settings, db: Session, run: Any, data: bytes, authority: Any, key: str
) -> dict[str, Any]:
    instance = service(settings, db, run.project_id, run.requested_by_user_id)
    instance.authorize(True)
    db.commit()
    binding = db.get(SqlLinearRun, run.id)
    if binding is None:
        raise RepositoryError("linear_run_not_found", 404)
    digest = hashlib.sha256(data).hexdigest()
    if binding.refresh_data:
        pending = binding.refresh_data
        if pending["key"] != key or pending["digest"] != digest:
            raise RepositoryError("linear_refresh_unacknowledged")
    else:
        state = instance.state()
        if binding.epoch != state.epoch:
            return {
                "error": "linear_epoch_changed",
                "instruction": "Finish this turn. Reconcile in a new turn after the restore.",
            }
        previous = instance.tx.linear.checkpoint(run.project_id, binding.current_checkpoint_id)
        assert previous is not None
        with instance.git.locked(initialize=False):
            authority()
            imported = instance.git.import_bundle(data, "main", previous.tree)
            changes = contribution(instance, previous, imported, run.id)
        commands, conflicts, _ = reconcile(instance, changes)
        if conflicts:
            return {"error": "linear_refresh_conflict", "paths": conflicts}
        latest = instance.checkpoint("Agent refresh input", identifier=uuid5(run.id, key))
        if latest.epoch != state.epoch or latest.sequence != state.sequence:
            return {
                "error": "linear_stale_revision",
                "instruction": "Inspect status and request refresh again.",
            }
        files = {str(f.id): content(f) for f in state.files if not f.deleted}
        for command in commands:
            kind, identifier = command["kind"], command["file_id"]
            if kind == "create":
                files[identifier] = command
            elif kind == "delete":
                files.pop(identifier)
            else:
                files[identifier].update(
                    {k: v for k, v in command.items() if k not in {"kind", "file_id"}}
                )
        db.commit()
        with instance.git.locked(initialize=False):
            instance.tx.linear.begin_write(instance.project_id)
            with tempfile.TemporaryDirectory(dir=instance.git.root) as temporary:
                env = {"GIT_INDEX_FILE": str(Path(temporary) / "index")}
                instance.git.git("read-tree", "--empty", env=env)
                records = bytearray()
                for file in files.values():
                    blob = (
                        instance.git.git(
                            "hash-object", "-w", "--stdin", data=decode(file["content_base64"])
                        )
                        .decode()
                        .strip()
                    )
                    mode = "100755" if file["executable"] else "100644"
                    records.extend(f"{mode} {blob}\t{file['path']}\0".encode())
                instance.git.git("update-index", "-z", "--index-info", data=bytes(records), env=env)
                tree = instance.git.git("write-tree", env=env).decode().strip()
            commit = instance.git.commit_tree(
                tree, [latest.tree], "Refresh isolated agent files", "Polycolab"
            )
            # Retain the prepared revision until a controller acknowledges installing it.
            instance.git.git("update-ref", f"refs/polycolab/refresh/{run.id}", commit)
            pending = {
                "key": key,
                "digest": digest,
                "generation": binding.refresh_generation + 1,
                "checkpoint_id": str(latest.id),
                "base": latest.tree,
                "commit": commit,
            }
            authority()
            binding.refresh_data = pending
            db.commit()
    with instance.git.locked(initialize=False):
        bundle = instance.git.bundle("main", commit=pending["commit"])
        authority()
    return {**pending, "bundle": encode(bundle)}


def acknowledge(settings: Settings, db: Session, run: Any, generation: int) -> dict[str, Any]:
    instance = service(settings, db, run.project_id, run.requested_by_user_id)
    instance.authorize(True)
    binding = db.get(SqlLinearRun, run.id)
    if binding is None:
        raise RepositoryError("linear_run_not_found", 404)
    if binding.refresh_generation == generation and binding.refresh_data is None:
        return {"generation": generation}
    pending = binding.refresh_data
    if pending is None or pending["generation"] != generation:
        raise RepositoryError("linear_refresh_generation_mismatch")
    binding.current_checkpoint_id = UUID(pending["checkpoint_id"])
    binding.refresh_generation = generation
    binding.refresh_data = None
    db.commit()
    return {"generation": generation}

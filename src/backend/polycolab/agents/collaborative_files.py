"""Snapshot execution and atomic integration of hosted collaborative file contributions."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.db.models import SqlAgentRun
from polycolab.db.models.collaborative import SqlChangeSet, SqlCollaborativeRun
from polycolab.entities.collaborative import CollaborativeFile, CollaborativeOperation
from polycolab.entities.repositories import RepositoryError
from polycolab.platform.config import Settings
from polycolab.projects.collaborative_factory import service
from polycolab.projects.collaborative_service import CollaborativeService, decode, encode


def content(file: CollaborativeFile) -> dict[str, Any]:
    return {
        "path": file.path,
        "content_base64": encode(file.content),
        "executable": file.executable,
        "binary": file.document is None,
    }


def pin(settings: Settings, db: Session, run: SqlAgentRun) -> dict[str, str]:

    instance = service(settings, db, run.project_id, run.requested_by_user_id)
    instance.authorize(True)
    db.commit()
    instance.state()
    binding = db.get(SqlCollaborativeRun, run.id)
    if binding is None:
        checkpoint = instance.checkpoint("Agent input", identifier=uuid5(run.id, "input"))
        binding = SqlCollaborativeRun(
            run_id=run.id,
            project_id=run.project_id,
            epoch=checkpoint.epoch,
            original_checkpoint_id=checkpoint.id,
            current_checkpoint_id=checkpoint.id,
        )
        db.add(binding)
        db.commit()
    pinned = instance.tx.collaborative.checkpoint(run.project_id, binding.current_checkpoint_id)
    assert pinned is not None
    return {
        "mode": "collaborative",
        "branch": "main",
        "commit": pinned.tree,
        "epoch": str(binding.epoch),
        "sequence": str(pinned.sequence),
        "checkpoint_id": str(pinned.id),
    }


def merge_text(
    instance: CollaborativeService, base: bytes, current: bytes, incoming: bytes
) -> bytes | None:
    if current == base or current == incoming:
        return incoming
    if incoming == base:
        return current
    if any(b"\0" in value for value in (base, current, incoming)):
        return None
    try:
        for value in (base, current, incoming):
            value.decode("utf-8")
    except UnicodeError:
        return None
    with tempfile.TemporaryDirectory(dir=instance.git.root) as temporary:
        paths = [Path(temporary) / name for name in ("current", "base", "incoming")]
        for path, value in zip(paths, (current, base, incoming), strict=True):
            path.write_bytes(value)
        try:
            return instance.git.git("merge-file", "-p", "--", *(str(p) for p in paths))
        except RepositoryError:
            return None


def reconcile(
    instance: CollaborativeService, changes: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    state = instance.state()
    files = {str(f.id): f for f in state.files if not f.deleted}
    commands: list[dict[str, Any]] = []
    conflicts: list[str] = []
    applied: list[dict[str, Any]] = []
    for change in changes:
        identifier, base, target = change["file_id"], change["base"], change["target"]
        current = files.get(identifier)
        name = (target or base)["path"]
        before = content(current) if current else None
        if base is None:
            if current or any(f.path == name for f in files.values()):
                conflicts.append(name)
                continue
            commands.append({"kind": "create", "file_id": identifier, **target})
            applied.append({"file_id": identifier, "base": None, "target": target})
            continue
        if target is None:
            if current and before != base:
                conflicts.append(name)
            elif current:
                commands.append({"kind": "delete", "file_id": identifier})
                applied.append({"file_id": identifier, "base": before, "target": None})
            continue
        if current is None:
            conflicts.append(name)
            continue
        if before and before["binary"] != target["binary"]:
            conflicts.append(name)
            continue
        merged = merge_text(
            instance,
            decode(base["content_base64"]),
            current.content,
            decode(target["content_base64"]),
        )
        path = current.path if target["path"] == base["path"] else target["path"]
        if merged is None or (current.path != base["path"] and path != current.path):
            conflicts.append(name)
            continue
        after = {
            **target,
            "content_base64": encode(merged),
            "path": path,
            "executable": current.executable
            if target["executable"] == base["executable"]
            else target["executable"],
        }
        if path != current.path:
            commands.append({"kind": "rename", "file_id": identifier, "path": path})
        if merged != current.content:
            commands.append(
                {"kind": "replace", "file_id": identifier, "content_base64": encode(merged)}
            )
        if after["executable"] != current.executable:
            commands.append(
                {"kind": "mode", "file_id": identifier, "executable": after["executable"]}
            )
        applied.append({"file_id": identifier, "base": before, "target": after})
    return commands, conflicts, applied


def apply_change_set(
    instance: CollaborativeService,
    db: Session,
    change_set: SqlChangeSet,
    authority: Callable[[], None] | None = None,
) -> int | None:
    # The batch: prefix is an immutable idempotency identity used by existing operations.
    if change_set.status == "applied":
        receipt = instance.tx.collaborative.receipt(
            instance.project_id, instance.user_id, f"batch:{change_set.id}"
        )
        return receipt.sequence if receipt else None
    instance.authorize(True)
    db.commit()
    current = instance.state()
    if change_set.epoch != current.epoch:
        if authority:
            authority()
        change_set.status, change_set.conflicts = (
            "pending",
            ["Project restored; reconcile with the latest workspace."],
        )
        db.commit()
        return None
    commands, conflicts, applied = reconcile(instance, change_set.changes)
    if conflicts:
        if authority:
            authority()
        change_set.status, change_set.conflicts = "pending", conflicts
        db.commit()
        return None
    if not commands:
        if authority:
            authority()
        change_set.status = "no_changes"
        db.commit()
        return current.sequence
    instance.checkpoint("Before AI changes", identifier=uuid5(change_set.id, "before"))

    def accepted(operation: CollaborativeOperation) -> None:
        change_set.status, change_set.conflicts, change_set.changes = "applied", [], applied
        if change_set.run_id:
            binding = db.get(SqlCollaborativeRun, change_set.run_id)
            assert binding is not None
            binding.applied_sequence = operation.sequence

    try:
        operation = instance.change(
            epoch=current.epoch,
            expected_sequence=current.sequence,
            key=f"batch:{change_set.id}",
            commands=commands,
            kind="agent",
            authority=authority,
            accepted=accepted,
        )
    except RepositoryError as error:
        db.rollback()
        if str(error) not in {
            "collaborative_stale_revision",
            "collaborative_epoch_changed",
            "repository_path_collision",
        }:
            raise
        if authority:
            authority()
        change_set.status, change_set.conflicts = (
            "pending",
            ["Shared files changed during integration. Reconcile with latest."],
        )
        db.commit()
        return None
    instance.automatic_checkpoint()
    return operation.sequence


def contribution(
    instance: CollaborativeService, checkpoint: Any, imported: str, run_id: Any
) -> list[dict[str, Any]]:
    entries = instance.git.entries(imported)
    before = {f["path"]: f for f in checkpoint.files}
    changes: list[dict[str, Any]] = []
    fields = (
        instance.git.git("diff", "--name-status", "-z", "-M", checkpoint.tree, imported)
        .decode()
        .split("\0")
    )
    renames: dict[str, str] = {}
    index = 0
    while index < len(fields) and fields[index]:
        kind = fields[index]
        if kind.startswith(("R", "C")):
            if kind.startswith("R"):
                renames[fields[index + 2]] = fields[index + 1]
            index += 3
        else:
            index += 2
    for path in sorted((before.keys() | entries.keys()) - set(renames.values())):
        old = before.get(renames.get(path, path))
        base = (
            {k: old[k] for k in ("path", "content_base64", "executable")}
            | {"binary": old["document"] is None}
            if old
            else None
        )
        target = None
        if path in entries:
            raw = instance.git.read(imported, path)
            try:
                raw.decode("utf-8")
                binary = b"\0" in raw
            except UnicodeError:
                binary = True
            target = {
                "path": path,
                "content_base64": encode(raw),
                "executable": entries[path][0] == "100755",
                "binary": binary,
            }
        if base != target:
            changes.append(
                {
                    "file_id": old["id"] if old else str(uuid5(run_id, path)),
                    "base": base,
                    "target": target,
                }
            )
    return changes


def save(
    settings: Settings, db: Session, run: SqlAgentRun, data: bytes, authority: Callable[[], None]
) -> dict[str, str]:
    binding = db.get(SqlCollaborativeRun, run.id)
    if binding is None:
        raise RepositoryError("collaborative_run_not_found", 404)
    if binding.refresh_data is not None:
        raise RepositoryError("collaborative_refresh_unacknowledged")
    instance = service(settings, db, run.project_id, run.requested_by_user_id)
    checkpoint = instance.tx.collaborative.checkpoint(run.project_id, binding.current_checkpoint_id)
    assert checkpoint is not None
    change_set = db.scalar(select(SqlChangeSet).where(SqlChangeSet.run_id == run.id))
    digest = hashlib.sha256(data).hexdigest()
    if change_set is not None and change_set.digest != digest:
        raise RepositoryError("collaborative_retry_mismatch")
    if change_set is None:
        db.commit()
        with instance.git.locked(initialize=False):
            instance.tx.collaborative.begin_write(instance.project_id)
            authority()
            imported = instance.git.import_bundle(data, "main", checkpoint.tree)
            changes = contribution(instance, checkpoint, imported, run.id)
            change_set = SqlChangeSet(
                id=uuid5(run.id, "result"),
                project_id=run.project_id,
                user_id=run.requested_by_user_id,
                run_id=run.id,
                epoch=binding.epoch,
                base_sequence=checkpoint.sequence,
                status="pending",
                digest=digest,
                changes=changes,
                conflicts=[],
            )
            stored_bytes = len(json.dumps(changes).encode())
            instance.check_quota(instance.state(), stored_bytes)
            authority()
            instance.tx.collaborative.add_storage(instance.project_id, stored_bytes)
            db.add(change_set)
            db.commit()
    sequence = apply_change_set(instance, db, change_set, authority)
    return {
        "commit": str(sequence or checkpoint.sequence),
        "application_status": change_set.status,
        "change_set_id": str(change_set.id),
    }

"""Authorized, durable collaborative changes and exact filesystem checkpoints."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4, uuid5

import httpx

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.entities.linear import LinearCheckpoint, LinearFile, LinearOperation, LinearState
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.projects.git_storage import TRANSFER_LIMIT, GitRepository, path_name
from polycolab.transaction import Transaction


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode()


def decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except ValueError:
        raise RepositoryError("linear_invalid_bytes", 422) from None


def file_value(file: LinearFile) -> dict[str, Any]:
    return {
        "id": str(file.id),
        "path": file.path,
        "content_base64": encode(file.content),
        "document": encode(file.document) if file.document is not None else None,
        "executable": file.executable,
        "deleted": file.deleted,
    }


def file_from(value: dict[str, Any]) -> LinearFile:
    return LinearFile(
        UUID(value["id"]),
        value["path"],
        decode(value["content_base64"]),
        decode(value["document"]) if value.get("document") is not None else None,
        value.get("executable", False),
        value.get("deleted", False),
    )


class CollaborationClient:
    def __init__(self, url: str, token: str):
        self.url, self.token = url.rstrip("/"), token

    def presence(self, value: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.post(
                    self.url + "/presence",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=value,
                )
                response.raise_for_status()
                peers = response.json()["peers"]
                if not isinstance(peers, list):
                    raise ValueError("invalid_presence")
                return peers
        except httpx.HTTPError, ValueError, KeyError:
            return []

    def prepare(self, project_id: UUID, values: list[dict[str, str]]) -> list[dict[str, str]]:
        try:
            with httpx.Client(timeout=15, trust_env=False) as client:
                response = client.post(
                    self.url + "/prepare",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"project_id": str(project_id), "documents": values},
                )
            if response.status_code == 422:
                raise RepositoryError("linear_invalid_update", 422)
            response.raise_for_status()
            result = response.json()["documents"]
            if not isinstance(result, list) or len(result) != len(values):
                raise ValueError
            return result
        except httpx.HTTPError, ValueError, KeyError:
            raise RepositoryError("collaboration_unavailable", 503) from None


class LinearService:
    def __init__(
        self,
        transaction: Transaction,
        git: GitRepository,
        project_id: UUID,
        user_id: UUID,
        collaboration: CollaborationClient,
    ):
        self.tx, self.git = transaction, git
        self.project_id, self.user_id = project_id, user_id
        self.collaboration = collaboration

    def authorize(
        self, write: bool = False, owner: bool = False, *, converting: bool = False
    ) -> None:
        action = (
            ProjectAction.MANAGE_SETTINGS
            if owner
            else ProjectAction.CREATE_RESEARCH
            if write
            else ProjectAction.VIEW
        )
        access = project_policy.require_scope(self.tx, self.project_id, self.user_id, action)
        if not converting and access.project.workspace_mode != "linear":
            raise RepositoryError("linear_mode_required", 409)
        if write and access.project.archived_at:
            raise RepositoryError("linear_writes_unavailable", 503)

    def state(self) -> LinearState:
        self.authorize()
        state = self.tx.linear.state(self.project_id)
        if state is None:
            self.tx.commit()
            with self.git.locked():
                self.tx.linear.begin_write(self.project_id)
                self.authorize()
                self.tx.linear.initialize(self.project_id)
                self.tx.commit()
            state = self.tx.linear.state(self.project_id)
        assert state is not None
        return state

    def change(
        self,
        *,
        epoch: int,
        expected_sequence: int | None,
        key: str,
        commands: list[dict[str, Any]],
        kind: str = "edit",
        owner: bool = False,
        new_epoch: bool = False,
        converting: bool = False,
        restored_checkpoint: UUID | None = None,
        authority: Callable[[], None] | None = None,
        accepted: Callable[[LinearOperation], None] | None = None,
    ) -> LinearOperation:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "epoch": epoch,
                    "expected_sequence": expected_sequence,
                    "commands": commands,
                    "kind": kind,
                    "restored_checkpoint": str(restored_checkpoint),
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        initialize = self.tx.linear.state(self.project_id) is None
        self.tx.commit()
        with self.git.locked(initialize=initialize):
            self.tx.linear.begin_write(self.project_id)
            self.authorize(True, owner, converting=converting)
            self.tx.linear.initialize(self.project_id)
            prior = self.tx.linear.receipt(self.project_id, self.user_id, key)
            if prior:
                if prior.digest != digest:
                    raise RepositoryError("linear_retry_mismatch")
                return prior
            state = self.tx.linear.state(self.project_id)
            assert state is not None
            if state.epoch != epoch:
                raise RepositoryError("linear_epoch_changed")
            if expected_sequence is not None and expected_sequence != state.sequence:
                raise RepositoryError("linear_stale_revision")
            if expected_sequence is None and any(c["kind"] != "update" for c in commands):
                raise RepositoryError("linear_expected_revision_required", 422)
            files = {f.id: f for f in state.files}
            changed: dict[UUID, LinearFile] = {}
            deltas: list[dict[str, Any]] = []
            for command in commands:
                identifier = UUID(command["file_id"])
                old = files.get(identifier)
                operation = command["kind"]
                if operation == "create":
                    if old is not None:
                        raise RepositoryError("linear_file_exists")
                    content = decode(command.get("content_base64", ""))
                    if command.get("binary", False):
                        document, update = None, None
                    else:
                        try:
                            text = content.decode("utf-8")
                        except UnicodeError:
                            raise RepositoryError("linear_invalid_text", 422) from None
                        prepared = self.collaboration.prepare(self.project_id, [{"text": text}])[0]
                        document, update = decode(prepared["state"]), prepared["update"]
                    file = LinearFile(
                        identifier,
                        path_name(command["path"]),
                        content,
                        document,
                        command.get("executable", False),
                    )
                else:
                    if old is None or old.deleted:
                        raise RepositoryError("linear_file_not_found", 404)
                    file, update = old, None
                    if operation in {"update", "replace"}:
                        if old.document is None:
                            if operation == "update":
                                raise RepositoryError("linear_binary_file", 422)
                            file = replace(old, content=decode(command["content_base64"]))
                        else:
                            candidate = {"state": encode(old.document)}
                            if operation == "update":
                                candidate["update"] = command["update"]
                            else:
                                try:
                                    candidate["text"] = decode(command["content_base64"]).decode(
                                        "utf-8"
                                    )
                                except UnicodeError:
                                    raise RepositoryError("linear_invalid_text", 422) from None
                            prepared = self.collaboration.prepare(self.project_id, [candidate])[0]
                            file = replace(
                                old,
                                content=prepared["text"].encode(),
                                document=decode(prepared["state"]),
                            )
                            update = prepared["update"]
                    elif operation == "rename":
                        file = replace(old, path=path_name(command["path"]))
                    elif operation == "delete":
                        file = replace(old, content=b"", document=None, deleted=True)
                    elif operation == "mode":
                        file = replace(old, executable=bool(command["executable"]))
                    else:
                        raise RepositoryError("linear_invalid_operation", 422)
                files[identifier] = file
                changed[identifier] = file
                delta = {
                    "id": str(identifier),
                    "path": file.path,
                    "deleted": file.deleted,
                    "executable": file.executable,
                    "binary": file.document is None,
                    "update": update,
                }
                if file.document is None:
                    delta["content_base64"] = encode(file.content)
                deltas.append(delta)
            live = [f for f in files.values() if not f.deleted]
            names = [f.path for f in live]
            if len(names) != len(set(names)) or any(
                "/".join(p.split("/")[:i]) in names
                for p in names
                for i in range(1, len(p.split("/")))
            ):
                raise RepositoryError("repository_path_collision", 422)
            if len(live) > 4096 or sum(len(f.content) for f in live) > TRANSFER_LIMIT:
                raise RepositoryError("repository_transfer_limit", 413)
            payload: dict[str, Any] = {"files": deltas}
            if restored_checkpoint is not None:
                payload["restored_checkpoint"] = str(restored_checkpoint)
            stored_bytes = state.stored_bytes + len(json.dumps(payload).encode())
            self.check_quota(replace(state, stored_bytes=stored_bytes, files=tuple(files.values())))
            value = LinearOperation(
                self.project_id,
                state.sequence + 1,
                epoch + int(new_epoch),
                self.user_id,
                key,
                digest,
                kind,
                payload,
                utc_now(),
            )
            self.authorize(True, owner, converting=converting)
            if authority:
                authority()
            self.tx.linear.accept(state, value, list(changed.values()), stored_bytes)
            if accepted:
                accepted(value)
            self.tx.commit()
            return value

    def check_quota(self, state: LinearState, extra: int = 0) -> None:
        materialized = self.git.root / f"{self.project_id}.linear"
        volume_bytes = sum(p.stat().st_size for p in materialized.rglob("*") if p.is_file())
        current_bytes = sum(len(f.content) + len(f.document or b"") for f in state.files)
        if (
            state.stored_bytes + current_bytes + self.git.size() + volume_bytes + extra
            > self.git.quota
        ):
            raise RepositoryError("repository_quota_exceeded", 413)

    def automatic_checkpoint(self) -> None:
        # An acknowledged SQL change must remain successful if its derived checkpoint fails.
        try:
            values = self.tx.linear.checkpoints(self.project_id)
            if not values or (utc_now() - values[0].created_at).total_seconds() >= 60:
                self.checkpoint()
        except RepositoryError, OSError:
            self.tx.rollback()
            logging.getLogger(__name__).warning(
                "Linear checkpoint deferred for %s", self.project_id
            )

    def checkpoint(
        self,
        title: str = "Automatic checkpoint",
        *,
        identifier: UUID | None = None,
        converting: bool = False,
    ) -> LinearCheckpoint:
        self.tx.commit()
        with self.git.locked(initialize=False):
            self.tx.linear.begin_write(self.project_id)
            self.authorize(converting=converting)
            state = self.tx.linear.state(self.project_id)
            if state is None:
                raise RepositoryError("linear_not_initialized")
            identifier = identifier or uuid4()
            existing = self.tx.linear.checkpoint(self.project_id, identifier)
            if existing:
                return existing
            files = [f for f in state.files if not f.deleted]
            checkpoint_bytes = len(json.dumps([file_value(f) for f in files]).encode())
            self.check_quota(state, checkpoint_bytes + sum(len(f.content) for f in files))
            with tempfile.TemporaryDirectory(dir=self.git.root) as temp:
                env = {"GIT_INDEX_FILE": str(Path(temp) / "index")}
                self.git.git("read-tree", "--empty", env=env)
                records = bytearray()
                for file in files:
                    blob = (
                        self.git.git("hash-object", "-w", "--stdin", data=file.content)
                        .decode()
                        .strip()
                    )
                    mode = "100755" if file.executable else "100644"
                    records.extend(f"{mode} {blob}\t{file.path}\0".encode())
                self.git.git("update-index", "-z", "--index-info", data=bytes(records), env=env)
                tree = self.git.git("write-tree", env=env).decode().strip()
            previous = self.tx.linear.checkpoints(self.project_id)
            commit = self.git.commit_tree(
                tree, [previous[0].tree] if previous else [], title, "Polycolab"
            )
            self.git.git("update-ref", f"refs/polycolab/linear/{identifier}", commit)
            value = LinearCheckpoint(
                identifier,
                self.project_id,
                state.sequence,
                state.epoch,
                title,
                commit,
                [file_value(f) for f in files],
                utc_now(),
            )
            self.materialize(state)
            self.tx.linear.add_checkpoint(value)
            self.tx.linear.add_storage(self.project_id, checkpoint_bytes)
            self.tx.commit()
            return value

    def materialize(self, state: LinearState) -> Path:
        # Immutable revision directories avoid readers observing partially replaced trees.
        root = self.git.root / f"{self.project_id}.linear"
        root.mkdir(mode=0o700, exist_ok=True)
        target = root / f"{state.epoch}-{state.sequence}"
        if target.exists():
            return target
        with tempfile.TemporaryDirectory(dir=root) as temp:
            staging = Path(temp) / "files"
            staging.mkdir()
            for file in state.files:
                if file.deleted:
                    continue
                path = staging / path_name(file.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as stream:
                    stream.write(file.content)
                    stream.flush()
                    os.fchmod(stream.fileno(), 0o755 if file.executable else 0o644)
                    os.fsync(stream.fileno())
            for directory, _, _ in os.walk(staging, topdown=False):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.replace(staging, target)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return target

    def restore(self, checkpoint_id: UUID, epoch: int, sequence: int, key: str) -> LinearOperation:
        self.authorize(True, True)
        target = self.tx.linear.checkpoint(self.project_id, checkpoint_id)
        if target is None:
            raise RepositoryError("linear_checkpoint_not_found", 404)
        state = self.state()
        prior = self.tx.linear.receipt(self.project_id, self.user_id, key)
        if prior:
            if prior.kind != "restore" or prior.payload.get("restored_checkpoint") != str(
                checkpoint_id
            ):
                raise RepositoryError("linear_retry_mismatch")
            return prior
        self.checkpoint("Before restore", identifier=uuid5(checkpoint_id, key))
        commands: list[dict[str, Any]] = [
            {"kind": "delete", "file_id": str(f.id)} for f in state.files if not f.deleted
        ]
        commands.extend(
            {
                "kind": "create",
                "file_id": str(uuid5(checkpoint_id, f"{key}:{f['id']}")),
                "path": f["path"],
                "content_base64": f["content_base64"],
                "binary": f["document"] is None,
                "executable": f["executable"],
            }
            for f in target.files
        )
        return self.change(
            epoch=epoch,
            expected_sequence=sequence,
            key=key,
            commands=commands,
            kind="restore",
            owner=True,
            new_epoch=True,
            restored_checkpoint=checkpoint_id,
        )

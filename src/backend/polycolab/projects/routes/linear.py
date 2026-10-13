"""Member-only HTTP and versioned WebSocket boundary for collaborative files."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import Field, ValidationError, model_validator
from starlette.concurrency import run_in_threadpool

from polycolab.access.authorization import (
    AuthorizationDenied,
    ProjectAction,
    ProjectNotFound,
    project_policy,
)
from polycolab.accounts.authentication import AuthenticationRequired, current_principal
from polycolab.accounts.identity import current_user
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.repositories import RepositoryError
from polycolab.projects.linear_service import LinearService, file_value
from polycolab.projects.repository_schemas import RepositoryModel
from polycolab.projects.routes.repository import RetryKey

router = APIRouter(prefix="/api/v1/projects/{project_id}/linear", tags=["linear workspaces"])


class LinearRevision(RepositoryModel):
    epoch: int = Field(ge=1)
    sequence: int = Field(ge=0)


class LinearCommand(RepositoryModel):
    kind: Literal["create", "update", "replace", "rename", "delete", "mode"]
    file_id: UUID
    path: str | None = Field(default=None, max_length=240)
    content_base64: str | None = Field(default=None, max_length=1_000_000)
    update: str | None = Field(default=None, max_length=1_000_000)
    binary: bool = False
    executable: bool = False

    @model_validator(mode="after")
    def required_fields(self) -> LinearCommand:
        if self.kind in {"create", "rename"} and self.path is None:
            raise ValueError("path is required")
        if self.kind == "replace" and self.content_base64 is None:
            raise ValueError("content_base64 is required")
        if self.kind == "update" and self.update is None:
            raise ValueError("update is required")
        return self


class LinearChange(RepositoryModel):
    epoch: int = Field(ge=1)
    expected_sequence: int | None = Field(default=None, ge=0)
    commands: list[LinearCommand] = Field(min_length=1, max_length=256)


class LinearFileRead(RepositoryModel):
    id: UUID
    path: str
    size: int
    executable: bool
    binary: bool


class LinearStateRead(LinearRevision):
    has_git_archive: bool
    writable: bool
    can_restore: bool
    files: list[LinearFileRead]


class LinearDocumentRead(RepositoryModel):
    id: UUID
    path: str
    content_base64: str
    document: str | None
    executable: bool
    deleted: bool
    epoch: int
    sequence: int


class LinearOperationRead(LinearRevision):
    user_id: UUID
    kind: str
    payload: dict[str, Any]
    created_at: str


class LinearCheckpointRead(LinearRevision):
    id: UUID
    title: str
    created_at: str


class CheckpointCreate(RepositoryModel):
    id: UUID
    title: str = Field(min_length=1, max_length=300)


class Restore(LinearRevision):
    checkpoint_id: UUID


def service(request: Request, db: DbSession, project_id: UUID, user_id: UUID) -> LinearService:
    from polycolab.projects.linear_factory import service as create_service

    return create_service(request.app.state.settings, db, project_id, user_id)


def state_read(instance: LinearService) -> LinearStateRead:
    state = instance.state()
    return LinearStateRead(
        has_git_archive=instance.tx.linear.has_archive(instance.project_id),
        epoch=state.epoch,
        sequence=state.sequence,
        writable=project_policy.can(
            instance.tx, instance.project_id, instance.user_id, ProjectAction.CREATE_RESEARCH
        ),
        can_restore=project_policy.can(
            instance.tx, instance.project_id, instance.user_id, ProjectAction.MANAGE_SETTINGS
        ),
        files=[
            LinearFileRead(
                id=f.id,
                path=f.path,
                size=len(f.content),
                executable=f.executable,
                binary=f.document is None,
            )
            for f in state.files
            if not f.deleted
        ],
    )


def operation_read(value: Any) -> LinearOperationRead:
    return LinearOperationRead(
        epoch=value.epoch,
        sequence=value.sequence,
        user_id=value.user_id,
        kind=value.kind,
        payload=value.payload,
        created_at=value.created_at.isoformat(),
    )


@router.get("", operation_id="getLinearProject")
def get_state(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> LinearStateRead:
    return state_read(service(request, db, project_id, user.id))


@router.get("/files/{file_id}", operation_id="getLinearFile")
def get_file(
    project_id: UUID, file_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> LinearDocumentRead:
    state = service(request, db, project_id, user.id).state()
    file = next((f for f in state.files if f.id == file_id and not f.deleted), None)
    if file is None:
        raise RepositoryError("linear_file_not_found", 404)
    return LinearDocumentRead(**file_value(file), epoch=state.epoch, sequence=state.sequence)


@router.post("/changes", operation_id="changeLinearFiles")
def changes(
    project_id: UUID,
    body: LinearChange,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> LinearOperationRead:
    instance = service(request, db, project_id, user.id)
    result = instance.change(
        epoch=body.epoch,
        expected_sequence=body.expected_sequence,
        key=key,
        commands=[c.model_dump(mode="json", exclude_none=True) for c in body.commands],
    )
    instance.automatic_checkpoint()
    return operation_read(result)


@router.get("/history", operation_id="getLinearHistory")
def history(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser, after: int = 0
) -> list[LinearOperationRead]:
    instance = service(request, db, project_id, user.id)
    instance.authorize()
    return [operation_read(v) for v in instance.tx.linear.operations(project_id, max(0, after))]


@router.get("/checkpoints", operation_id="listLinearCheckpoints")
def checkpoints(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> list[LinearCheckpointRead]:
    instance = service(request, db, project_id, user.id)
    instance.authorize()
    return [
        LinearCheckpointRead(
            id=v.id,
            epoch=v.epoch,
            sequence=v.sequence,
            title=v.title,
            created_at=v.created_at.isoformat(),
        )
        for v in instance.tx.linear.checkpoints(project_id)
    ]


@router.post("/checkpoints", operation_id="createLinearCheckpoint")
def checkpoint(
    project_id: UUID, body: CheckpointCreate, request: Request, db: DbSession, user: CurrentUser
) -> LinearCheckpointRead:
    instance = service(request, db, project_id, user.id)
    instance.authorize(True)
    instance.state()
    value = instance.checkpoint(body.title, identifier=body.id)
    return LinearCheckpointRead(
        id=value.id,
        epoch=value.epoch,
        sequence=value.sequence,
        title=value.title,
        created_at=value.created_at.isoformat(),
    )


@router.get("/checkpoints/{checkpoint_id}/files", operation_id="getLinearCheckpointFiles")
def checkpoint_files(
    project_id: UUID, checkpoint_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> list[LinearDocumentRead]:
    instance = service(request, db, project_id, user.id)
    instance.authorize()
    value = instance.tx.linear.checkpoint(project_id, checkpoint_id)
    if value is None:
        raise RepositoryError("linear_checkpoint_not_found", 404)
    return [
        LinearDocumentRead(**f, epoch=value.epoch, sequence=value.sequence) for f in value.files
    ]


@router.post("/restore", operation_id="restoreLinearCheckpoint")
def restore(
    project_id: UUID,
    body: Restore,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> LinearOperationRead:
    return operation_read(
        service(request, db, project_id, user.id).restore(
            body.checkpoint_id, body.epoch, body.sequence, key
        )
    )


@router.websocket("/events")
async def events(socket: WebSocket, project_id: UUID) -> None:
    settings = socket.app.state.settings
    origins = {str(o).rstrip("/") for o in settings.allowed_origins}
    if settings.public_app_origin:
        origins.add(str(settings.public_app_origin).rstrip("/"))
    if socket.headers.get("origin", "").rstrip("/") not in origins:
        await socket.close(code=1008)
        return
    await socket.accept()
    cursor = 0
    connection_id = str(uuid4())
    last_presence = 0.0
    active_file: str | None = None
    try:
        initial = json.loads(await asyncio.wait_for(socket.receive_text(), 10))
        if initial.get("version") != 1:
            await socket.close(code=1008)
            return
        scope = {**socket.scope, "type": "http", "method": "GET"}
        if initial.get("authorization"):
            scope["headers"] = [(k, v) for k, v in scope["headers"] if k != b"authorization"] + [
                (b"authorization", str(initial["authorization"]).encode())
            ]
        request = Request(scope)

        def access() -> UUID:
            principal = current_principal(request)
            with socket.app.state.session_factory() as db:
                tx = SqlAlchemyTransaction(db)
                user = current_user(tx, principal)
                project_policy.require_scope(tx, project_id, user.id, ProjectAction.VIEW)
                return user.id

        user_id = await run_in_threadpool(access)
        cursor = max(0, int(initial.get("after", 0)))
        while True:
            await run_in_threadpool(access)
            if asyncio.get_running_loop().time() - last_presence >= 3:

                def peers(active_file: str | None = active_file) -> list[dict[str, Any]]:
                    with socket.app.state.session_factory() as db:
                        user = current_user(SqlAlchemyTransaction(db), current_principal(request))
                        instance = service(request, db, project_id, user.id)
                        state = instance.state()
                        selected = (
                            active_file
                            if any(str(f.id) == active_file and not f.deleted for f in state.files)
                            else None
                        )
                        return instance.collaboration.presence(
                            {
                                "project_id": str(project_id),
                                "connection_id": connection_id,
                                "user_id": str(user.id),
                                "label": user.display_name or "Project member",
                                "file_id": selected,
                            }
                        )

                await socket.send_json(
                    {"kind": "presence", "peers": await run_in_threadpool(peers)}
                )
                last_presence = asyncio.get_running_loop().time()

            def poll(after: int = cursor) -> list[dict[str, Any]]:
                with socket.app.state.session_factory() as db:
                    instance = service(request, db, project_id, user_id)
                    instance.authorize()
                    return [
                        operation_read(v).model_dump(mode="json")
                        for v in instance.tx.linear.operations(project_id, after)
                    ]

            for operation in await run_in_threadpool(poll):
                await socket.send_json(
                    {
                        **operation,
                        "version": 1,
                        "kind": "operation",
                        "operation_kind": operation["kind"],
                    }
                )
                cursor = operation["sequence"]
            try:
                raw = await asyncio.wait_for(socket.receive_text(), 0.1)
            except TimeoutError:
                continue
            if len(raw) > 1_100_000:
                await socket.close(code=1009)
                return
            message = json.loads(raw)
            if message.get("kind") == "update":
                try:
                    body = LinearChange.model_validate(message["body"])
                    key = str(message["request_id"])
                    if not 1 <= len(key) <= 200:
                        raise ValueError

                    def write(body: LinearChange = body, key: str = key) -> dict[str, Any]:
                        with socket.app.state.session_factory() as db:
                            return changes(
                                project_id,
                                body,
                                key,
                                request,
                                db,
                                current_user(SqlAlchemyTransaction(db), current_principal(request)),
                            ).model_dump(mode="json")

                    result = await run_in_threadpool(write)
                    await socket.send_json(
                        {**result, "version": 1, "kind": "ack", "request_id": key}
                    )
                except RepositoryError as error:
                    if error.status >= 500 or error.code == "repository_busy":
                        await socket.close(code=1013)
                        return
                    await socket.send_json(
                        {
                            "version": 1,
                            "kind": "rejected",
                            "request_id": message.get("request_id"),
                            "error": str(error),
                        }
                    )
            elif message.get("kind") == "presence":
                active_file = str(UUID(message["file_id"])) if message.get("file_id") else None
                last_presence = 0.0
            elif message.get("kind") == "ping":
                await socket.send_json({"version": 1, "kind": "pong"})
    except (
        WebSocketDisconnect,
        AuthenticationRequired,
        AuthorizationDenied,
        ProjectNotFound,
        RepositoryError,
        ValidationError,
        ValueError,
        KeyError,
        TimeoutError,
    ) as error:
        try:
            retryable = isinstance(error, RepositoryError) and (
                error.status >= 500 or error.code == "repository_busy"
            )
            await socket.close(code=1013 if retryable else 1008)
        except RuntimeError:
            pass


class ConversionRequest(RepositoryModel):
    worktree_id: UUID
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")


@router.get("/conversion-preview", operation_id="previewLinearConversion")
def conversion_preview(
    project_id: UUID, worktree_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> dict[str, Any]:
    from polycolab.projects.linear_conversion import preview

    return preview(request.app.state.settings, db, project_id, user.id, worktree_id)


@router.post("/convert", operation_id="convertProjectToLinear")
def conversion(
    project_id: UUID,
    body: ConversionRequest,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> LinearStateRead:
    from polycolab.projects.linear_conversion import convert

    convert(
        request.app.state.settings, db, project_id, user.id, body.worktree_id, body.revision, key
    )
    return state_read(service(request, db, project_id, user.id))


class BatchRead(RepositoryModel):
    id: UUID
    run_id: UUID | None
    status: str
    epoch: int
    base_sequence: int
    changes: list[dict[str, Any]]
    conflicts: list[str]


class BatchResolution(LinearChange):
    commands: list[LinearCommand] = Field(default_factory=list, max_length=256)


def private_batch(instance: LinearService, db: DbSession, batch_id: UUID) -> Any:
    from polycolab.db.models.linear import SqlLinearBatch

    instance.authorize()
    batch = db.get(SqlLinearBatch, batch_id)
    if (
        batch is None
        or batch.project_id != instance.project_id
        or batch.user_id != instance.user_id
    ):
        raise RepositoryError("linear_batch_not_found", 404)
    return batch


@router.get("/batches", operation_id="listLinearBatches")
def batches(
    project_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> list[BatchRead]:
    from sqlalchemy import select

    from polycolab.db.models.linear import SqlLinearBatch

    instance = service(request, db, project_id, user.id)
    instance.authorize()
    return [
        BatchRead.model_validate(batch, from_attributes=True)
        for batch in db.scalars(
            select(SqlLinearBatch)
            .where(SqlLinearBatch.project_id == project_id, SqlLinearBatch.user_id == user.id)
            .limit(100)
        )
    ]


@router.post("/batches/{batch_id}/retry", operation_id="retryLinearBatch")
def retry_batch(
    project_id: UUID, batch_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> BatchRead:
    from polycolab.agents.linear_files import apply_batch

    instance = service(request, db, project_id, user.id)
    batch = private_batch(instance, db, batch_id)
    if batch.status == "pending":
        apply_batch(instance, db, batch)
    return BatchRead.model_validate(batch, from_attributes=True)


@router.post("/batches/{batch_id}/resolve", operation_id="resolveLinearBatch")
def resolve_batch(
    project_id: UUID,
    batch_id: UUID,
    body: BatchResolution,
    key: RetryKey,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> LinearOperationRead:
    instance = service(request, db, project_id, user.id)
    batch = private_batch(instance, db, batch_id)
    if batch.status != "pending" and instance.tx.linear.receipt(project_id, user.id, key) is None:
        raise RepositoryError("linear_batch_already_resolved")
    if body.expected_sequence is None:
        raise RepositoryError("linear_expected_revision_required", 422)

    def accepted(operation: Any) -> None:
        batch.status = "resolved"
        batch.conflicts = []

    result = instance.change(
        epoch=body.epoch,
        expected_sequence=body.expected_sequence,
        key=key,
        commands=[c.model_dump(mode="json", exclude_none=True) for c in body.commands],
        kind="resolution",
        accepted=accepted,
    )
    instance.automatic_checkpoint()
    return operation_read(result)


@router.post("/batches/{batch_id}/revert", operation_id="revertLinearBatch")
def revert_batch(
    project_id: UUID, batch_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> BatchRead:
    from uuid import uuid5

    from polycolab.agents.linear_files import apply_batch
    from polycolab.db.models.linear import SqlLinearBatch

    instance = service(request, db, project_id, user.id)
    batch = private_batch(instance, db, batch_id)
    instance.authorize(True)
    if batch.status != "applied":
        raise RepositoryError("linear_batch_not_applied")
    identifier = uuid5(batch_id, "revert")
    inverse = db.get(SqlLinearBatch, identifier)
    if inverse is None:
        inverse = SqlLinearBatch(
            id=identifier,
            project_id=project_id,
            user_id=user.id,
            epoch=batch.epoch,
            base_sequence=instance.state().sequence,
            status="pending",
            changes=[
                {
                    "file_id": str(uuid5(identifier, change["file_id"]))
                    if change["target"] is None
                    else change["file_id"],
                    "base": change["target"],
                    "target": change["base"],
                }
                for change in batch.changes
            ],
            conflicts=[],
        )
        db.commit()
        with instance.git.locked(initialize=False):
            instance.tx.linear.begin_write(project_id)
            instance.authorize(True)
            stored_bytes = len(json.dumps(inverse.changes).encode())
            instance.check_quota(instance.state(), stored_bytes)
            instance.tx.linear.add_storage(project_id, stored_bytes)
            db.add(inverse)
            db.commit()
    apply_batch(instance, db, inverse)
    return BatchRead.model_validate(inverse, from_attributes=True)


@router.get("/checkpoints/{checkpoint_id}/diff", operation_id="diffLinearCheckpoint")
def checkpoint_diff(
    project_id: UUID, checkpoint_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> str:
    import difflib

    from polycolab.projects.linear_service import file_from

    instance = service(request, db, project_id, user.id)
    state = instance.state()
    checkpoint = instance.tx.linear.checkpoint(project_id, checkpoint_id)
    if checkpoint is None:
        raise RepositoryError("linear_checkpoint_not_found", 404)
    before = {file["path"]: file_from(file) for file in checkpoint.files}
    after = {file.path: file for file in state.files if not file.deleted}
    output = [f"Checkpoint {checkpoint.sequence} → current revision {state.sequence}\n"]
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old and new and old.content == new.content and old.executable == new.executable:
            continue
        if (old and old.document is None) or (new and new.document is None):
            output.append(f"Binary file changed: {name}\n")
            continue
        output.extend(
            difflib.unified_diff(
                (old.content.decode() if old else "").splitlines(keepends=True),
                (new.content.decode() if new else "").splitlines(keepends=True),
                fromfile=f"checkpoint/{name}",
                tofile=f"current/{name}",
            )
        )
        if old and new and old.executable != new.executable:
            output.append(f"Executable mode changed: {name}\n")
    return "".join(output)

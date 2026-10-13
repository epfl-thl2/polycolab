"""Private hosted artifact transport, fenced before and after object-store access."""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from polycolab.access.authorization import ProjectAction
from polycolab.agents.context import manifest_artifacts, manifest_for_run
from polycolab.agents.exports import reserve_export, verify_export
from polycolab.agents.routes.runtime import (
    LeaseRequest,
    RuntimeApiConflict,
    _authorize_worker,
    _lease_or_conflict,
)
from polycolab.agents.routes.sessions import _run_scope
from polycolab.agents.runtime.artifacts import ExportDeclaration, UploadRequest
from polycolab.agents.sessions import LeaseLost
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.routes.private import artifact_storage, download
from polycolab.db.models import (
    SqlArtifact,
    SqlHostedRunArtifact,
)
from polycolab.entities.artifacts import ArtifactStorageError
from polycolab.entities.enums import AgentRunStatus, ArtifactState

router = APIRouter()


def _reserve(request: Request, run_id: UUID, payload: UploadRequest) -> artifacts.StoredArtifact:
    with request.app.state.session_factory() as session:
        try:
            return reserve_export(session, run_id, payload, request.app.state.settings)
        except LeaseLost:
            raise RuntimeApiConflict("lease_lost") from None


def _verify(request: Request, run_id: UUID, payload: UploadRequest, artifact_id: UUID) -> None:
    with request.app.state.session_factory() as session:
        try:
            verify_export(session, run_id, payload, artifact_id)
        except LeaseLost:
            raise RuntimeApiConflict("lease_lost") from None


@router.post("/internal/hosted/runs/{run_id}/artifacts", include_in_schema=False)
async def upload_export(
    run_id: UUID, payload: Annotated[UploadRequest, Query()], request: Request
) -> dict[str, str]:
    _authorize_worker(request)
    data = bytearray()
    async with asyncio.timeout(30):
        async for chunk in request.stream():
            if len(data) + len(chunk) > payload.byte_length:
                raise HTTPException(413, "artifact_size_limit")
            data.extend(chunk)
    if len(data) != payload.byte_length or hashlib.sha256(data).hexdigest() != payload.sha256:
        raise RuntimeApiConflict("artifact_integrity_mismatch")
    row = await run_in_threadpool(_reserve, request, run_id, payload)

    def store() -> None:
        with artifact_storage(request) as storage:
            storage.put_verified(row.storage_key, BytesIO(data), row.integrity)

    try:
        await run_in_threadpool(store)
    except ArtifactStorageError:
        raise RuntimeApiConflict("artifact_storage_unavailable") from None
    await run_in_threadpool(_verify, request, run_id, payload, row.id)
    return {"artifact_id": str(row.id)}


@router.get("/internal/hosted/runs/{run_id}/inputs/{artifact_id}", include_in_schema=False)
def input_bytes(
    run_id: UUID, artifact_id: UUID, payload: Annotated[LeaseRequest, Query()], request: Request
) -> Response:
    _authorize_worker(request)
    with request.app.state.session_factory() as session:
        run = _lease_or_conflict(
            session, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        allowed = manifest_artifacts(session, manifest=manifest_for_run(session, run=run))
        if artifact_id not in {item.id for item in allowed}:
            raise RuntimeApiConflict("artifact_not_in_manifest")
        row = artifacts.read(
            session,
            project_id=run.project_id,
            user_id=run.requested_by_user_id,
            artifact_id=artifact_id,
        )
    with artifact_storage(request) as storage:
        data = storage.get_verified(row.storage_key, row.integrity)
    with request.app.state.session_factory() as session:
        _lease_or_conflict(
            session, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        artifacts.read(
            session,
            project_id=run.project_id,
            user_id=run.requested_by_user_id,
            artifact_id=artifact_id,
        )
    return Response(data, media_type="application/octet-stream")


class HostedArtifactRead(ExportDeclaration):
    artifact_id: UUID
    sha256: str
    byte_length: int


@router.get(
    "/api/v1/agent-runs/{run_id}/artifacts",
    response_model=list[HostedArtifactRead],
    operation_id="listHostedRunArtifacts",
)
def list_exports(run_id: UUID, db: DbSession, user: CurrentUser) -> list[HostedArtifactRead]:
    run = _run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.VIEW)
    if run.requested_by_user_id != user.id:
        raise HTTPException(404, "not_found")
    if run.status != AgentRunStatus.COMPLETED:
        return []
    return [
        HostedArtifactRead(
            artifact_id=artifact.id,
            path=binding.path,
            display_name=binding.display_name,
            media_type=artifact.media_type,
            sha256=artifact.sha256,
            byte_length=artifact.byte_length,
        )
        for binding, artifact in db.execute(
            select(SqlHostedRunArtifact, SqlArtifact)
            .join(SqlArtifact)
            .where(
                SqlHostedRunArtifact.run_id == run_id, SqlArtifact.state == ArtifactState.COMMITTED
            )
            .order_by(SqlHostedRunArtifact.path)
        )
    ]


@router.get(
    "/api/v1/agent-runs/{run_id}/artifacts/{artifact_id}/content",
    response_class=Response,
    operation_id="downloadHostedRunArtifact",
)
def download_export(
    run_id: UUID, artifact_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> Response:
    run = _run_scope(db, run_id=run_id, user_id=user.id, action=ProjectAction.VIEW)
    if run.requested_by_user_id != user.id:
        raise HTTPException(404, "not_found")
    binding = db.get(SqlHostedRunArtifact, artifact_id)
    if binding is None or binding.run_id != run_id or run.status != AgentRunStatus.COMPLETED:
        raise HTTPException(404, "not_found")
    return download(run.project_id, artifact_id, request, user, db)

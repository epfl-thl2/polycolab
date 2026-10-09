"""Authenticated private artifact proxy; registration belongs to integration."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from polycolab.access.actors import Actor
from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.artifacts import service as artifacts
from polycolab.artifacts.contracts import (
    ArtifactAttachmentPage,
    ArtifactAttachmentRead,
    ArtifactAttachmentWrite,
    ArtifactRead,
    ArtifactUploadDeclaration,
    private_download_headers,
)
from polycolab.artifacts.storage import ArtifactStorage, ArtifactStorageError, configured_storage
from polycolab.platform.config import Settings
from polycolab.research.records import project_access


def private_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/api/v1/workspaces/{workspace_id}/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(private_no_store)],
)


@contextmanager
def artifact_storage(request: Request) -> Iterator[ArtifactStorage]:
    injected = getattr(request.app.state, "artifact_storage", None)
    if injected is not None:
        yield injected
        return
    settings: Settings = request.app.state.settings
    if not settings.artifact_storage_configured:
        raise HTTPException(503, "artifact_storage_unavailable")
    store = configured_storage(settings)
    try:
        yield store
    finally:
        store.close()


def _read(row: artifacts.StoredArtifact) -> ArtifactRead:
    return ArtifactRead(
        id=row.id,
        sha256=row.integrity.sha256,
        byte_length=row.integrity.byte_length,
        media_type=row.media_type,
        state=row.state,
        expires_at=row.expires_at,
    )


def _stage(
    request: Request,
    workspace_id: UUID,
    user_id: UUID,
    declaration: ArtifactUploadDeclaration,
    data: bytes,
    source_revision_id: UUID | None,
    actor: Actor | None = None,
) -> ArtifactRead:
    with request.app.state.session_factory() as session:
        row = artifacts.reserve(
            session,
            project_id=workspace_id,
            user_id=user_id,
            declaration=declaration,
            settings=request.app.state.settings,
            source_revision_id=source_revision_id,
            actor=actor,
        )
    try:
        with artifact_storage(request) as store:
            store.put_verified(row.storage_key, BytesIO(data), row.integrity)
    except ArtifactStorageError as exc:
        code = str(exc)
        status = 422 if code in {"artifact_length_mismatch", "artifact_digest_mismatch"} else 503
        raise HTTPException(status, code) from None
    with request.app.state.session_factory() as session:
        return _read(
            artifacts.verified(
                session, project_id=workspace_id, user_id=user_id, artifact_id=row.id
            )
        )


@router.post(
    "",
    response_model=ArtifactRead,
    status_code=201,
    operation_id="uploadArtifact",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    workspace_id: UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    sha256: Annotated[str, Query(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")],
    byte_length: Annotated[int, Query(ge=0, le=16 * 1024 * 1024)],
    media_type: Annotated[str, Query(max_length=127)] = "application/octet-stream",
    source_object_version_id: UUID | None = None,
) -> ArtifactRead:
    settings: Settings = request.app.state.settings
    if byte_length > settings.artifact_max_bytes:
        raise HTTPException(413, "artifact_size_limit")
    try:
        declaration = ArtifactUploadDeclaration(
            sha256=sha256, byte_length=byte_length, media_type=media_type
        )
    except ValidationError:
        raise HTTPException(422, "artifact_invalid_declaration") from None
    user_id = user.id
    # Authorize before consuming bytes, then release the request transaction.
    project_access(session, workspace_id, user_id, write=True)
    session.rollback()
    data = bytearray()
    try:
        async with asyncio.timeout(settings.artifact_request_timeout_seconds):
            async for chunk in request.stream():
                if len(data) + len(chunk) > byte_length:
                    raise HTTPException(413, "artifact_size_limit")
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "artifact_upload_timeout") from None
    if len(data) != byte_length:
        raise HTTPException(422, "artifact_length_mismatch")
    return await run_in_threadpool(
        _stage, request, workspace_id, user_id, declaration, bytes(data), source_object_version_id
    )


@router.get("", response_model=ArtifactAttachmentPage, operation_id="pageArtifactAttachments")
def list_attachments(
    workspace_id: UUID,
    user: CurrentUser,
    session: DbSession,
    object_version_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> ArtifactAttachmentPage:
    return artifacts.list_attachments(
        session,
        project_id=workspace_id,
        user_id=user.id,
        revision_id=object_version_id,
        limit=limit,
        cursor=cursor,
    )


@router.get("/{artifact_id}", response_model=ArtifactRead, operation_id="readArtifact")
def metadata(
    workspace_id: UUID, artifact_id: UUID, user: CurrentUser, session: DbSession
) -> ArtifactRead:
    return _read(
        artifacts.read(
            session,
            project_id=workspace_id,
            user_id=user.id,
            artifact_id=artifact_id,
            include_staging=True,
        )
    )


@router.post(
    "/{artifact_id}/attachments",
    response_model=ArtifactAttachmentRead,
    operation_id="attachArtifact",
)
def attach(
    workspace_id: UUID,
    artifact_id: UUID,
    payload: ArtifactAttachmentWrite,
    user: CurrentUser,
    session: DbSession,
) -> ArtifactAttachmentRead:
    return ArtifactAttachmentRead(
        id=artifacts.attach(
            session,
            project_id=workspace_id,
            user_id=user.id,
            artifact_id=artifact_id,
            revision_id=payload.object_version_id,
            role=payload.role,
            attempt_revision_id=payload.attempt_object_version_id,
        )
    )


@router.get(
    "/{artifact_id}/content",
    operation_id="downloadArtifact",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
def download(
    workspace_id: UUID, artifact_id: UUID, request: Request, user: CurrentUser, session: DbSession
) -> Response:
    user_id = user.id
    row = artifacts.read(session, project_id=workspace_id, user_id=user_id, artifact_id=artifact_id)
    session.rollback()
    try:
        with artifact_storage(request) as store:
            data = store.get_verified(row.storage_key, row.integrity)
    except ArtifactStorageError:
        raise HTTPException(503, "artifact_storage_unavailable") from None
    # Revocation during retrieval must prevent returning the buffered bytes.
    with request.app.state.session_factory() as fresh:
        artifacts.read(fresh, project_id=workspace_id, user_id=user_id, artifact_id=artifact_id)
    return Response(content=data, headers=private_download_headers())

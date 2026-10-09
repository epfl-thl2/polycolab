"""Separate private controller boundary. Not included in public OpenAPI.

This module supplies lifecycle/byte services, never a sandbox or process launcher.
Both the configured credential and the execution gate are required to claim work.
"""

import asyncio
import secrets
from io import BytesIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from polycolab.app.dependencies import DbSession
from polycolab.artifacts.contracts import private_download_headers
from polycolab.artifacts.routes.private import artifact_storage
from polycolab.artifacts.storage import ArtifactStorageError
from polycolab.entities.time import utc_now
from polycolab.verification import service as verification
from polycolab.verification.contracts import (
    AttemptBinding,
    ControllerCompletion,
    OutputStageRequest,
)
from polycolab.verification.routes.boundary import VerificationRoute
from polycolab.verification.version_contracts import VersionControllerClaim, VersionJobRead


def controller(
    request: Request, response: Response, authorization: Annotated[str | None, Header()] = None
) -> str:
    settings = request.app.state.settings
    current = settings.verification_controller_token
    previous = settings.verification_controller_previous_token
    expiry = settings.verification_controller_previous_token_expires_at
    if current is None:
        raise HTTPException(503, "verification_controller_unavailable")
    token = (authorization or "").removeprefix("Bearer ")
    valid = secrets.compare_digest(token, current.get_secret_value())
    if previous is not None and expiry is not None and verification.utc(expiry) > utc_now():
        valid = secrets.compare_digest(token, previous.get_secret_value()) or valid
    if not (authorization or "").startswith("Bearer ") or not valid:
        raise HTTPException(401, "invalid_controller_credential")
    response.headers["Cache-Control"] = "private, no-store"
    return str(settings.verification_controller_id)


Controller = Annotated[str, Depends(controller)]
router = APIRouter(
    route_class=VerificationRoute,
    prefix="/internal/verification",
    include_in_schema=False,
    dependencies=[Depends(controller)],
)


@router.post("/claim", response_model=VersionControllerClaim | None)
def claim(
    request: Request, identity: Controller, session: DbSession
) -> VersionControllerClaim | None:
    if not request.app.state.settings.feature_verification_execution_enabled:
        raise HTTPException(503, "verification_execution_disabled")
    verification.recover(session)
    result = verification.claim(
        session, controller_id=identity, settings=request.app.state.settings
    )
    return VersionControllerClaim.from_stored(result) if result is not None else None


@router.post("/renew", response_model=VersionControllerClaim)
def renew(
    payload: AttemptBinding, request: Request, identity: Controller, session: DbSession
) -> VersionControllerClaim:
    result = verification.renew(
        session, binding=payload, controller_id=identity, settings=request.app.state.settings
    )
    return VersionControllerClaim.from_stored(result)


@router.post("/recover")
def recover(identity: Controller, session: DbSession) -> dict[str, int]:
    return {"recovered": verification.recover(session)}


@router.get("/jobs/{job_id}/attempts/{attempt_id}/inputs/{position}")
def input_content(
    job_id: UUID,
    attempt_id: UUID,
    position: int,
    generation: Annotated[int, Query(ge=1, le=2**31 - 1)],
    request: Request,
    identity: Controller,
) -> Response:
    binding = AttemptBinding(job_id=job_id, attempt_id=attempt_id, generation=generation)
    with request.app.state.session_factory() as session:
        value = verification.input_bytes(
            session, binding=binding, controller_id=identity, position=position
        )
    data = value.data
    if value.artifact is not None:
        try:
            with artifact_storage(request) as store:
                data = store.get_verified(value.artifact.storage_key, value.artifact.integrity)
        except ArtifactStorageError:
            raise HTTPException(503, "verification_storage_unavailable") from None
    with request.app.state.session_factory() as session:
        verification.input_bytes(
            session, binding=binding, controller_id=identity, position=position
        )
    assert data is not None
    return Response(data, headers=private_download_headers())


def _upload(
    request: Request, identity: str, payload: OutputStageRequest, data: bytes
) -> dict[str, str]:
    with request.app.state.session_factory() as session:
        row = verification.stage(
            session, payload=payload, controller_id=identity, settings=request.app.state.settings
        )
    try:
        with artifact_storage(request) as store:
            store.put_verified(row.storage_key, BytesIO(data), row.integrity)
    except ArtifactStorageError as exc:
        mismatch = str(exc) in {"artifact_length_mismatch", "artifact_digest_mismatch"}
        raise HTTPException(422 if mismatch else 503, "verification_output_storage_error") from None
    with request.app.state.session_factory() as session:
        verification.stage(
            session, payload=payload, controller_id=identity, settings=request.app.state.settings
        )
    return {"artifact_id": str(row.id)}


@router.put("/jobs/{job_id}/attempts/{attempt_id}/outputs")
async def stage(
    job_id: UUID,
    attempt_id: UUID,
    request: Request,
    identity: Controller,
    generation: int = Query(ge=1),
    path: str = Query(max_length=240),
    role: str = Query(max_length=16),
    sha256: str = Query(min_length=64, max_length=64),
    byte_length: int = Query(ge=0, le=16 * 1024 * 1024),
) -> dict[str, str]:
    from pydantic import ValidationError

    try:
        payload = OutputStageRequest.model_validate(
            dict(
                job_id=job_id,
                attempt_id=attempt_id,
                generation=generation,
                path=path,
                role=role,
                sha256=sha256,
                byte_length=byte_length,
            )
        )
    except ValidationError:
        raise HTTPException(422, "invalid_output_declaration") from None
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data) + len(chunk) > min(
                    byte_length, request.app.state.settings.artifact_max_bytes
                ):
                    raise HTTPException(413, "verification_output_too_large")
                data.extend(chunk)
    except TimeoutError:
        raise HTTPException(408, "verification_upload_timeout") from None
    if len(data) != byte_length:
        raise HTTPException(422, "verification_output_length")
    return await run_in_threadpool(_upload, request, identity, payload, bytes(data))


@router.post("/complete", response_model=VersionJobRead)
def complete(
    payload: ControllerCompletion, request: Request, identity: Controller
) -> VersionJobRead:
    with request.app.state.session_factory() as session:
        rows = verification.completion_artifacts(session, payload=payload, controller_id=identity)
    if rows:
        try:
            with artifact_storage(request) as store:
                for row in rows:
                    store.get_verified(row.storage_key, row.integrity)
        except ArtifactStorageError:
            raise HTTPException(503, "verification_storage_unavailable") from None
    with request.app.state.session_factory() as session:
        result = verification.complete(
            session, payload=payload, controller_id=identity, verified_artifacts=rows
        )
        return VersionJobRead.from_stored(result)

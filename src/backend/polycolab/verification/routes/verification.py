"""Human verification routes; shared registration is Research's integration step."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.db.models import SqlVerificationEnvironment
from polycolab.entities.enums import VerificationLanguage
from polycolab.verification import environments as verification_environments
from polycolab.verification import service as verification
from polycolab.verification.contracts import (
    EventRead,
    ResourceLimits,
    RetryRequest,
)
from polycolab.verification.limits import QuotaExceeded
from polycolab.verification.routes.boundary import VerificationRoute
from polycolab.verification.schemas import VerificationEnvironmentPage, VerificationEnvironmentRead
from polycolab.verification.version_contracts import VersionJobRead, VersionJobSubmitRequest


def enabled(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(
    prefix="/api/v1/projects/{project_id}/verification-jobs",
    tags=["verification"],
    route_class=VerificationRoute,
    dependencies=[Depends(enabled)],
)

environment_router = APIRouter(
    prefix="/api/v1/projects/{project_id}/verification-environments",
    tags=["verification"],
    route_class=VerificationRoute,
    dependencies=[Depends(enabled)],
)


def _environment_read(value: SqlVerificationEnvironment) -> VerificationEnvironmentRead:
    return VerificationEnvironmentRead(
        id=value.id,
        language=value.language,
        image_digest=value.image_digest,
        toolchain_version=value.toolchain_version,
        dependency_lock_digest=value.dependency_lock_digest,
        build_digest=value.build_digest,
        platform_identity=value.platform_identity,
        limits=ResourceLimits(
            cpu_count=value.max_cpu_count,
            cpu_seconds=value.max_cpu_seconds,
            wall_seconds=value.max_wall_seconds,
            memory_bytes=value.max_memory_bytes,
            process_count=value.max_process_count,
            disk_bytes=value.max_disk_bytes,
            output_bytes=value.max_output_bytes,
            log_bytes=value.max_log_bytes,
            output_files=value.max_output_files,
        ),
        created_at=value.created_at,
        availability_changed_at=value.availability_changed_at,
    )


@environment_router.get(
    "",
    response_model=VerificationEnvironmentPage,
    operation_id="discoverVerificationEnvironments",
)
def environments(
    project_id: UUID,
    user: CurrentUser,
    session: DbSession,
    after: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    language: VerificationLanguage | None = None,
) -> VerificationEnvironmentPage:
    items, next_after = verification_environments.available(
        session,
        project_id=project_id,
        user_id=user.id,
        after=after,
        limit=limit,
        language=language,
    )
    return VerificationEnvironmentPage(
        items=[_environment_read(item) for item in items], next_after=next_after
    )


@router.post(
    "", response_model=VersionJobRead, status_code=201, operation_id="submitVerificationJob"
)
def submit(
    project_id: UUID,
    payload: VersionJobSubmitRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> VersionJobRead:
    if project_id != payload.submission.project_id:
        raise HTTPException(422, "verification_project_mismatch")
    try:
        result = verification.submit(
            session,
            user_id=user.id,
            submission=payload.submission.historical_command(),
            retry_key=payload.retry_key,
            settings=request.app.state.settings,
        )
        return VersionJobRead.from_stored(result)
    except QuotaExceeded:
        raise HTTPException(
            429, "verification_quota_exceeded", headers={"Retry-After": "60"}
        ) from None


@router.get("/{job_id}", response_model=VersionJobRead, operation_id="getVerificationJob")
def inspect(
    project_id: UUID, job_id: UUID, user: CurrentUser, session: DbSession
) -> VersionJobRead:
    return VersionJobRead.from_stored(
        verification.inspect(session, job_id=job_id, project_id=project_id, user_id=user.id)
    )


@router.get(
    "/{job_id}/events", response_model=tuple[EventRead, ...], operation_id="getVerificationEvents"
)
def events(
    project_id: UUID,
    job_id: UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
) -> tuple[EventRead, ...]:
    return verification.events(
        session,
        job_id=job_id,
        project_id=project_id,
        user_id=user.id,
        after=after_sequence,
        limit=limit,
        settings=request.app.state.settings,
    )


@router.post(
    "/{job_id}/cancel", response_model=VersionJobRead, operation_id="cancelVerificationJob"
)
def cancel(project_id: UUID, job_id: UUID, user: CurrentUser, session: DbSession) -> VersionJobRead:
    return VersionJobRead.from_stored(
        verification.cancel(session, job_id=job_id, project_id=project_id, user_id=user.id)
    )


@router.post(
    "/{job_id}/rerun",
    response_model=VersionJobRead,
    status_code=201,
    operation_id="rerunVerificationJob",
)
def rerun(
    project_id: UUID,
    job_id: UUID,
    payload: RetryRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
) -> VersionJobRead:
    try:
        result = verification.rerun(
            session,
            job_id=job_id,
            project_id=project_id,
            user_id=user.id,
            retry_key=payload.retry_key,
            settings=request.app.state.settings,
        )
        return VersionJobRead.from_stored(result)
    except QuotaExceeded:
        raise HTTPException(
            429, "verification_quota_exceeded", headers={"Retry-After": "60"}
        ) from None

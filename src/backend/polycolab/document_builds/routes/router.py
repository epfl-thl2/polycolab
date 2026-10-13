"""Project/worktree-scoped compilation and credential-only worker transport."""

import asyncio
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import Annotated, Literal
from uuid import UUID
from zipfile import ZIP_STORED, ZipFile

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.artifacts.routes.private import artifact_storage, private_no_store
from polycolab.db.stores.document_builds import SqlBuildStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.document_builds.routes.schemas import (
    BuildAttempt,
    BuildClaimRead,
    BuildCompletion,
    BuildList,
    BuildRead,
    BuildRequest,
    WorkerClaim,
    WorkerReady,
)
from polycolab.document_builds.service import BuildService
from polycolab.entities.document_builds import BuildError, BuildLimits, DocumentBuild
from polycolab.entities.time import utc_now
from polycolab.projects.routes.repository import RetryKey
from polycolab.projects.routes.repository import service as repository_service

router = APIRouter(tags=["document builds"], dependencies=[Depends(private_no_store)])
BASE = "/api/v1/projects/{project_id}/worktrees/{worktree_id}/latex-builds"


def limits(request: Request) -> BuildLimits:
    s = request.app.state.settings
    return BuildLimits(
        s.latex_capacity,
        s.latex_project_queue,
        s.latex_project_max_bytes,
        s.latex_execution_seconds,
        s.latex_queue_seconds,
        s.latex_retention_days,
    )


@contextmanager
def service(request: Request, db: DbSession) -> Iterator[BuildService]:
    with artifact_storage(request) as storage:
        yield BuildService(
            SqlAlchemyTransaction(db),
            SqlBuildStore(db),
            storage,
            request.app.state.settings.latex_image,
            limits(request),
        )


def read(build: DocumentBuild) -> BuildRead:
    result = BuildRead.model_validate(build)
    result.pdf_available = build.status == "succeeded" and bool(
        build.outputs.get("pdf") and build.outputs["pdf"].verified
    )
    result.log_available = bool(build.outputs.get("log") and build.outputs["log"].verified)
    return result


@router.post(BASE, response_model=BuildRead, status_code=202, operation_id="createLatexBuild")
def create(
    project_id: UUID,
    worktree_id: UUID,
    body: BuildRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    key: RetryKey,
) -> BuildRead:
    repo = repository_service(request, db, project_id, user.id).native_service()
    with service(request, db) as builds:
        with repo.open():
            builds.authorize(project_id, user.id, True)
            previous = builds.retry(
                project_id, worktree_id, user.id, key, body.revision, body.main_file, body.engine
            )
            if previous:
                return read(builds.get(project_id, worktree_id, previous.id, user.id))
            task = repo.store.task(project_id, worktree_id)
            if repo.require_available(task) != body.revision:
                raise BuildError("latex_stale_revision")
            entries = repo.git.entries(body.revision)
            if body.main_file not in entries or not body.main_file.lower().endswith(".tex"):
                raise BuildError("latex_main_file_required", 422)
            db.commit()
            archive = BytesIO()
            with ZipFile(archive, "w", compression=ZIP_STORED) as output:
                for path in entries:
                    output.writestr(path, repo.git.read(body.revision, path))
                    if archive.tell() > 16 * 1024 * 1024:
                        raise BuildError("latex_input_limit", 413)
            if archive.tell() > 16 * 1024 * 1024:
                raise BuildError("latex_input_limit", 413)
        return read(
            builds.submit(
                project_id,
                worktree_id,
                user.id,
                key,
                body.revision,
                body.main_file,
                body.engine,
                archive.getvalue(),
            )
        )


@router.get(BASE, response_model=BuildList, operation_id="listLatexBuilds")
def listing(
    project_id: UUID, worktree_id: UUID, request: Request, db: DbSession, user: CurrentUser
) -> BuildList:
    with service(request, db) as builds:
        builds.authorize(project_id, user.id)
        # Worktree identity remains required even when no builds exist.
        repository_service(request, db, project_id, user.id).store.task(project_id, worktree_id)
        builds.transaction.commit()
        builds.recover()
        available = builds.available()
        return BuildList(
            available=available,
            builds=[read(item) for item in builds.store.recent(project_id, worktree_id, utc_now())],
        )


@router.get(BASE + "/{build_id}", response_model=BuildRead, operation_id="getLatexBuild")
def get(
    project_id: UUID,
    worktree_id: UUID,
    build_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> BuildRead:
    with service(request, db) as builds:
        builds.get(project_id, worktree_id, build_id, user.id)
        builds.transaction.commit()
        builds.recover()
        return read(builds.get(project_id, worktree_id, build_id, user.id))


@router.post(BASE + "/{build_id}/cancel", response_model=BuildRead, operation_id="cancelLatexBuild")
def cancel(
    project_id: UUID,
    worktree_id: UUID,
    build_id: UUID,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> BuildRead:
    with service(request, db) as builds:
        return read(builds.cancel(project_id, worktree_id, build_id, user.id))


@router.get(
    BASE + "/{build_id}/outputs/{kind}",
    operation_id="downloadLatexOutput",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "text/plain": {}}}},
)
def download(
    project_id: UUID,
    worktree_id: UUID,
    build_id: UUID,
    kind: Literal["pdf", "log"],
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> Response:
    with service(request, db) as builds:
        build = builds.get(project_id, worktree_id, build_id, user.id)
        if kind not in build.outputs or (kind == "pdf" and build.status != "succeeded"):
            raise BuildError("latex_output_unavailable", 404)
        builds.transaction.commit()
        data = builds.read_blob(build.outputs[kind])
        builds.get(project_id, worktree_id, build_id, user.id)
        return Response(
            data,
            media_type="application/pdf" if kind == "pdf" else "text/plain",
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "sandbox",
                "Content-Disposition": f'attachment; filename="document.{kind}"',
            },
        )


def worker_auth(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
    expected = request.app.state.settings.latex_worker_token
    if (
        not expected
        or not authorization
        or not secrets.compare_digest(authorization, "Bearer " + expected.get_secret_value())
    ):
        raise HTTPException(401, "latex_worker_unauthorized")


worker = APIRouter(
    prefix="/internal/latex",
    include_in_schema=False,
    dependencies=[Depends(worker_auth), Depends(private_no_store)],
)


@worker.post("/ready", status_code=204)
def ready(body: WorkerReady, request: Request, db: DbSession) -> None:
    with service(request, db) as builds:
        builds.ready(body.image)


@worker.post("/claim", response_model=BuildClaimRead | None)
def claim(body: WorkerClaim, request: Request, db: DbSession) -> BuildClaimRead | None:
    with service(request, db) as builds:
        build = builds.claim(body.worker_id)
        if not build:
            return None
        assert build.generation and build.deadline
        return BuildClaimRead(
            id=build.id,
            generation=build.generation,
            main_file=build.main_file,
            engine=build.engine,
            image=build.image,
            deadline=build.deadline,
            input_sha256=build.input.sha256,
        )


@worker.post("/{build_id}/heartbeat", status_code=204)
def heartbeat(build_id: UUID, body: BuildAttempt, request: Request, db: DbSession) -> None:
    with service(request, db) as builds:
        builds.heartbeat(build_id, body.generation)


@worker.get("/{build_id}/input")
def source(build_id: UUID, generation: UUID, request: Request, db: DbSession) -> Response:
    with service(request, db) as builds:
        return Response(
            builds.input_bytes(build_id, generation),
            media_type="application/zip",
            headers={"Cache-Control": "no-store"},
        )


@worker.put("/{build_id}/outputs/{kind}", status_code=204)
async def upload(
    build_id: UUID, kind: Literal["pdf", "log"], generation: UUID, request: Request, db: DbSession
) -> None:
    data = bytearray()
    maximum = 1024 * 1024 if kind == "log" else 16 * 1024 * 1024
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data) > maximum:
                    raise BuildError("latex_output_limit", 413)
    except TimeoutError:
        raise BuildError("latex_upload_timeout", 408) from None

    def apply() -> None:
        with service(request, db) as builds:
            builds.upload(build_id, generation, kind, bytes(data))

    await run_in_threadpool(apply)


@worker.post("/{build_id}/complete", status_code=204)
def complete(build_id: UUID, body: BuildCompletion, request: Request, db: DbSession) -> None:
    with service(request, db) as builds:
        builds.finish(build_id, body.generation, body.status, body.error)


@worker.post("/{build_id}/release", status_code=204)
def release(build_id: UUID, body: BuildAttempt, request: Request, db: DbSession) -> None:
    with service(request, db) as builds:
        builds.release(build_id, body.generation)


router.include_router(worker)

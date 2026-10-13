"""Private repository transport for exactly pinned, currently authorized hosted runs."""

from __future__ import annotations

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from polycolab.access.authorization import ProjectAction, project_policy
from polycolab.agents.routes.runtime import (
    LeaseRequest,
    RuntimeApiConflict,
    _authorize_worker,
    _lease_or_conflict,
)
from polycolab.agents.sessions import LeaseLost, _locked_run, _require_live_lease, _utc
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.entities.enums import AgentRunStatus
from polycolab.entities.repositories import RepositoryError
from polycolab.entities.time import utc_now
from polycolab.projects.git_storage import TRANSFER_LIMIT
from polycolab.projects.routes.repository import service

router = APIRouter(include_in_schema=False)


@router.get("/internal/hosted/runs/{run_id}/repository")
def checkout(run_id: UUID, request: Request, payload: Annotated[LeaseRequest, Query()]) -> Response:
    _authorize_worker(request)
    with request.app.state.session_factory() as db:
        run = _lease_or_conflict(
            db, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        from polycolab.db.models.linear import SqlLinearRun

        linear = db.get(SqlLinearRun, run_id)
        if linear is not None:
            from polycolab.projects.routes.linear import service as linear_service

            live = linear_service(request, db, run.project_id, run.requested_by_user_id)
            live.authorize()
            checkpoint = live.tx.linear.checkpoint(run.project_id, linear.current_checkpoint_id)
            assert checkpoint is not None
            with live.git.locked():
                data = live.git.bundle("main", commit=checkpoint.tree)
                _lease_or_conflict(
                    db, run_id, payload, request.app.state.settings.runtime_lease_seconds
                )
                live.authorize()
            return Response(
                data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"}
            )
        instance = service(request, db, run.project_id, run.requested_by_user_id)
        with instance.open() as git:
            binding = instance.store.run(run_id)
            if binding is None:
                raise RepositoryError("repository_not_in_run", 403)
            db.commit()
            data = git.bundle(
                binding.branch or f"sessions/{binding.session_id}",
                commit=binding.input_revision or binding.input_commit,
            )
            _lease_or_conflict(
                db, run_id, payload, request.app.state.settings.runtime_lease_seconds
            )
            instance.authorize()
        return Response(
            data, media_type="application/octet-stream", headers={"Cache-Control": "no-store"}
        )


def _save(request: Request, run_id: UUID, payload: LeaseRequest, data: bytes) -> dict[str, str]:
    with request.app.state.session_factory() as db:
        run = _lease_or_conflict(
            db, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        project_id, user_id = run.project_id, run.requested_by_user_id
        db.commit()
        instance = service(request, db, project_id, user_id)

        def authority() -> None:
            require_authority(request, db, run_id, payload, project_id, user_id)

        from polycolab.db.models.linear import SqlLinearRun

        if db.get(SqlLinearRun, run_id) is not None:
            from polycolab.agents.linear_files import save

            return save(request.app.state.settings, db, run, data, authority)
        return {"commit": instance.export_run(run_id, data, authority)}


@router.post("/internal/hosted/runs/{run_id}/repository")
async def save(
    run_id: UUID, request: Request, payload: Annotated[LeaseRequest, Query()]
) -> dict[str, str]:
    _authorize_worker(request)
    data = bytearray()
    async with asyncio.timeout(30):
        async for chunk in request.stream():
            if len(data) + len(chunk) > TRANSFER_LIMIT:
                raise RepositoryError("repository_transfer_limit", 413)
            data.extend(chunk)
    return await run_in_threadpool(_save, request, run_id, payload, bytes(data))


def require_authority(
    request: Request,
    db: Session,
    run_id: UUID,
    payload: LeaseRequest,
    project_id: UUID,
    user_id: UUID,
) -> None:
    project_policy.require_scope(
        SqlAlchemyTransaction(db), project_id, user_id, ProjectAction.RUN_AGENTS
    )
    current = _locked_run(db, run_id)
    try:
        _require_live_lease(
            current,
            worker_id=payload.worker_id,
            lease_generation=payload.lease_generation,
            now=utc_now(),
        )
    except LeaseLost:
        raise RuntimeApiConflict("lease_lost") from None
    if (
        current.status != AgentRunStatus.RUNNING
        or current.cancel_requested_at is not None
        or (current.deadline_at and _utc(current.deadline_at) <= utc_now())
    ):
        raise RuntimeApiConflict("lease_lost")


@router.get("/internal/hosted/runs/{run_id}/workspace-status")
def workspace_status(
    run_id: UUID, request: Request, payload: Annotated[LeaseRequest, Query()]
) -> dict[str, object]:
    from polycolab.agents.linear_refresh import status

    _authorize_worker(request)
    with request.app.state.session_factory() as db:
        run = _lease_or_conflict(
            db, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        require_authority(request, db, run_id, payload, run.project_id, run.requested_by_user_id)
        return status(request.app.state.settings, db, run)


class RefreshLease(LeaseRequest):
    key: str


class RefreshAckLease(LeaseRequest):
    generation: int


@router.post("/internal/hosted/runs/{run_id}/workspace-refresh")
async def workspace_refresh(
    run_id: UUID, request: Request, payload: Annotated[RefreshLease, Query()]
) -> dict[str, object]:
    from polycolab.agents.linear_refresh import prepare

    _authorize_worker(request)
    key = payload.key
    if not 1 <= len(key) <= 200:
        raise RepositoryError("linear_invalid_refresh_key", 422)
    data = bytearray()
    async with asyncio.timeout(30):
        async for chunk in request.stream():
            if len(data) + len(chunk) > TRANSFER_LIMIT:
                raise RepositoryError("repository_transfer_limit", 413)
            data.extend(chunk)

    def refresh() -> dict[str, object]:
        with request.app.state.session_factory() as db:
            run = _lease_or_conflict(
                db, run_id, payload, request.app.state.settings.runtime_lease_seconds
            )
            project_id, user_id = run.project_id, run.requested_by_user_id
            db.commit()

            def authority() -> None:
                require_authority(request, db, run_id, payload, project_id, user_id)

            return prepare(request.app.state.settings, db, run, bytes(data), authority, key)

    return await run_in_threadpool(refresh)


@router.post("/internal/hosted/runs/{run_id}/workspace-refresh-ack")
def workspace_refresh_ack(
    run_id: UUID, request: Request, payload: Annotated[RefreshAckLease, Query()]
) -> dict[str, object]:
    from polycolab.agents.linear_refresh import acknowledge

    _authorize_worker(request)
    with request.app.state.session_factory() as db:
        run = _lease_or_conflict(
            db, run_id, payload, request.app.state.settings.runtime_lease_seconds
        )
        require_authority(request, db, run_id, payload, run.project_id, run.requested_by_user_id)
        return acknowledge(request.app.state.settings, db, run, payload.generation)

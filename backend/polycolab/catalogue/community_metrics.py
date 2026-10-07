"""Opt-in, local-only export of the community process's own pool observations."""

from __future__ import annotations

import asyncio
import os
import socket
import stat
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from threading import Event, Thread

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.engine import Engine
from starlette.types import Lifespan

from polycolab.accounts.authentication import (
    AuthenticationRequired,
    IdentityVerifier,
    current_principal,
    verifier_from_settings,
)
from polycolab.db.session import make_session_factory
from polycolab.operations.pool_telemetry import PoolMeter
from polycolab.platform.config import Settings


def create_metrics_app(
    settings: Settings,
    engine: Engine,
    meter: PoolMeter,
    *,
    identity_verifier: IdentityVerifier | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
) -> FastAPI:
    """No public/application routes, credential adapters or separate database pool."""
    app = FastAPI(
        openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False, lifespan=lifespan
    )
    app.state.identity_verifier = identity_verifier or verifier_from_settings(
        settings, make_session_factory(engine)
    )

    @app.middleware("http")
    async def protect_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response: Response
        try:
            # This GET-only surface has no request body. Do not read or log it.
            if not settings.operator_diagnostics_enabled:
                response = PlainTextResponse("Not found", status_code=404)
            elif (
                request.headers.get("transfer-encoding")
                or request.headers.get("content-length", "0") != "0"
            ):
                response = PlainTextResponse("Request body not accepted", status_code=400)
            else:
                response = await call_next(request)
        except Exception:
            # Identity/database failures must not emit driver URLs or credentials.
            response = PlainTextResponse("Diagnostics unavailable", status_code=503)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/internal/v1/metrics", include_in_schema=False)
    def metrics(request: Request) -> PlainTextResponse:
        if not settings.operator_diagnostics_enabled:
            return PlainTextResponse("Not found", status_code=404)
        try:
            principal = current_principal(request)
        except AuthenticationRequired:
            return PlainTextResponse("Unauthenticated", status_code=401)
        if principal.subject not in settings.operator_diagnostics_subjects:
            return PlainTextResponse("Forbidden", status_code=403)
        return PlainTextResponse(
            meter.render(engine), media_type="text/plain; version=0.0.4; charset=utf-8"
        )

    return app


@contextmanager
def private_metrics_socket(path: Path) -> Iterator[socket.socket]:
    """Bind a new socket; never unlink an existing or subsequently replaced path."""
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError("metrics socket requires a canonical absolute path")
    parent = path.parent.stat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != os.getuid()
        or stat.S_IMODE(parent.st_mode) != 0o700
    ):
        raise ValueError("metrics socket requires an owned mode-700 directory")
    # bind() atomically refuses existing names, including stale sockets/symlinks.
    # The private directory protects the short bind-to-chmod interval.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        identity = path.lstat()
        try:
            path.chmod(0o600)
            listener.listen(8)
            yield listener
        finally:
            try:
                current = path.lstat()
            except FileNotFoundError:
                pass
            else:
                if (
                    stat.S_ISSOCK(current.st_mode)
                    and current.st_dev == identity.st_dev
                    and current.st_ino == identity.st_ino
                ):
                    path.unlink()


def run_metrics_consumer(
    settings: Settings,
    engine: Engine,
    meter: PoolMeter,
    socket_path: Path,
    consume: Callable[[], None],
    stopped: Event,
) -> None:
    """One server and one consumer thread, sharing one instrumented engine."""
    if not settings.operator_diagnostics_enabled:
        raise ValueError("operator diagnostics must be explicitly enabled")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        thread = Thread(target=consume, name="community-consumer")
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            # Finish the current transaction before the caller disposes the engine.
            # This deliberately does not claim a hard deadline for blocked SQL.
            await asyncio.to_thread(thread.join)

    with private_metrics_socket(socket_path) as listener:
        app = create_metrics_app(settings, engine, meter, lifespan=lifespan)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                access_log=False,
                log_config=None,
                proxy_headers=False,
                server_header=False,
                ws="none",
                workers=1,
                limit_concurrency=4,
                timeout_keep_alive=2,
                timeout_graceful_shutdown=5,
                lifespan="on",
            )
        )
        server.run(sockets=[listener])
        if not server.started:
            raise RuntimeError("community diagnostics failed to start")

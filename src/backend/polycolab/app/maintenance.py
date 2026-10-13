"""Background jobs for the single-process application deployment."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from threading import Event, Thread

from fastapi import FastAPI

from polycolab.artifacts.gc import consume as collect_artifacts
from polycolab.artifacts.storage import configured_storage
from polycolab.catalogue.community_consumer import consume as consume_notifications
from polycolab.execution.reconciler import consume as recover_execution


@asynccontextmanager
async def maintenance_lifespan(app: FastAPI) -> AsyncIterator[None]:
    stopped = Event()
    factory = app.state.session_factory
    threads = [
        Thread(target=consume_notifications, args=(factory, stopped), name="notifications"),
        Thread(target=recover_execution, args=(factory, stopped), name="execution-recovery"),
    ]
    storage = None
    started: list[Thread] = []
    try:
        if app.state.settings.artifact_storage_configured:
            storage = configured_storage(app.state.settings)
            threads.append(
                Thread(
                    target=partial(
                        collect_artifacts,
                        app.state.transaction_factory,
                        storage,
                        stopped,
                        grace_seconds=app.state.settings.artifact_gc_grace_seconds,
                    ),
                    name="artifact-cleanup",
                )
            )
        for thread in threads:
            thread.start()
            started.append(thread)
        yield
    finally:
        stopped.set()
        # Finish in-flight transactions before closing storage or the shared pool.
        for thread in started:
            await asyncio.to_thread(thread.join)
        if storage is not None:
            storage.close()
        app.state.engine.dispose()

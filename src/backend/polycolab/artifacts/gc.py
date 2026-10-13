"""Application-owned staging cleanup; never runs inside a sandbox/controller."""

import logging
import signal
from threading import Event

from polycolab.artifacts.cleanup import sweep_page
from polycolab.artifacts.storage import ArtifactStorage, configured_storage
from polycolab.db.session import make_engine, make_session_factory
from polycolab.db.transaction import make_transaction_factory
from polycolab.platform.config import get_settings
from polycolab.transaction import TransactionFactory


def consume(
    factory: TransactionFactory,
    storage: ArtifactStorage,
    stopped: Event,
    *,
    grace_seconds: int,
) -> None:
    cursor = None
    while not stopped.is_set():
        try:
            page = sweep_page(factory, storage, grace_seconds=grace_seconds, after=cursor)
            cursor = page.next_cursor
            if page.failure_count:
                logging.getLogger(__name__).warning("artifact_gc_storage_failed")
            stopped.wait(1 if cursor else 30)
        except Exception:
            logging.getLogger(__name__).error("artifact_gc_batch_failed")
            stopped.wait(5)


def main() -> None:
    settings = get_settings()
    storage = configured_storage(settings)
    engine = make_engine(settings)
    factory = make_transaction_factory(make_session_factory(engine))
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        consume(factory, storage, stopped, grace_seconds=settings.artifact_gc_grace_seconds)
    finally:
        storage.close()
        engine.dispose()


if __name__ == "__main__":
    main()

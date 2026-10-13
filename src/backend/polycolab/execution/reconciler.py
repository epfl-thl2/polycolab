"""Application-owned recovery; requires no running executor or provider credentials."""

import logging
import signal
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from polycolab.agents.recovery import reconcile
from polycolab.db.session import make_engine, make_session_factory
from polycolab.execution.hosts import release_elapsed
from polycolab.model_gateway.hosted import recover_pending
from polycolab.platform.config import get_settings


def consume(factory: sessionmaker[Session], stopped: Event) -> None:
    while not stopped.is_set():
        try:
            with factory() as session:
                recover_pending(session)
                reconcile(session)
                release_elapsed(session)
        except Exception:
            logging.getLogger(__name__).error("hosted_recovery_batch_failed")
        stopped.wait(5)


def main() -> None:
    engine = make_engine(get_settings())
    factory = make_session_factory(engine)
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        consume(factory, stopped)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()

"""Application-owned outbox consumer; not the database-free hosted agent worker."""

import argparse
import logging
import signal
from pathlib import Path
from threading import Event

from sqlalchemy.orm import Session, sessionmaker

from polycolab.catalogue.community_metrics import run_metrics_consumer
from polycolab.db.session import make_engine, make_session_factory
from polycolab.operations.pool_telemetry import PoolMeter
from polycolab.operations.telemetry import PoolRole
from polycolab.platform.config import get_settings
from polycolab.research.notifications import process_one


def consume(factory: sessionmaker[Session], stopped: Event) -> None:
    while not stopped.is_set():
        try:
            with factory() as session:
                worked = process_one(session)
            if not worked:
                stopped.wait(1)
        except Exception:
            logging.getLogger(__name__).error("community_consumer_batch_failed")
            stopped.wait(5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-uds",
        type=Path,
        help="opt-in operator metrics socket in an existing owned mode-700 directory",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    if args.metrics_uds is not None and not settings.operator_diagnostics_enabled:
        parser.error("--metrics-uds requires OPERATOR_DIAGNOSTICS_ENABLED")
    pool_meter = PoolMeter(settings, PoolRole.COMMUNITY)
    engine = make_engine(settings, pool_class=pool_meter.pool_class)
    factory = make_session_factory(engine)
    stopped = Event()
    previous_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        # Uvicorn restores and re-raises signals after graceful shutdown. Keep
        # these handlers installed until socket cleanup and engine disposal finish.
        for sig in previous_handlers:
            signal.signal(sig, lambda *_: stopped.set())
        if args.metrics_uds is not None:
            run_metrics_consumer(
                settings,
                engine,
                pool_meter,
                args.metrics_uds,
                lambda: consume(factory, stopped),
                stopped,
            )
        else:
            consume(factory, stopped)
    except Exception:
        logging.getLogger(__name__).error("community_consumer_service_failed")
        return 1
    finally:
        engine.dispose()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

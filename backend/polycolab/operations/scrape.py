"""Protected scrape orchestration; no provider or execution-service work."""

from __future__ import annotations

from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from polycolab.operations.telemetry import (
    community_outbox_snapshot,
    publish_community_outbox_snapshot,
    record_community_outbox_snapshot_error,
)
from polycolab.platform.observability import Metrics


class CommunityScrape:
    """App-local snapshot counters; each response renders its own completed read."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._registry = Metrics()
        self._publish_lock = Lock()

    def render(self) -> str:
        # Authorization belongs to the calling protected route, before this read.
        # No rendering or telemetry lock is held across database access.
        try:
            with self._factory() as session:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET TRANSACTION READ ONLY"))
                snapshot = community_outbox_snapshot(session)
        except Exception:
            snapshot = None
        with self._publish_lock:
            if snapshot is None:
                record_community_outbox_snapshot_error(self._registry)
            else:
                publish_community_outbox_snapshot(self._registry, snapshot)
            # Serialize publish/render so concurrent requests cannot substitute
            # another request's snapshot or leave stale gauges on error.
            return self._registry.render_prometheus()

"""Process-local QueuePool acquisition observations; no SQL or connection labels."""

from threading import Lock
from time import monotonic

from sqlalchemy.engine import Engine
from sqlalchemy.exc import TimeoutError
from sqlalchemy.pool import PoolProxiedConnection, QueuePool

from polycolab.operations.telemetry import PoolCheckoutOutcome, PoolRole, PoolTelemetry
from polycolab.platform.config import Settings
from polycolab.platform.observability import Metrics


class PoolMeter:
    def __init__(self, settings: Settings, role: PoolRole) -> None:
        self._registry = Metrics()
        self._telemetry = PoolTelemetry(self._registry, role)
        self._lock = Lock()
        self.pool_class: type[QueuePool] | None = None
        if settings.database_url.startswith("sqlite"):
            return
        self._telemetry.publish_configuration(
            size=settings.database_pool_size, max_overflow=settings.database_max_overflow
        )
        meter = self

        class ObservedQueuePool(QueuePool):
            # Use the public acquisition boundary so queue waits, connection
            # creation and pre-ping are included. A checkout event fires too late.
            # The closure survives QueuePool.recreate() after engine disposal.
            def connect(self) -> PoolProxiedConnection:
                started = monotonic()
                try:
                    connection = super().connect()
                except TimeoutError:
                    meter._observe(started, PoolCheckoutOutcome.TIMEOUT)
                    raise
                meter._observe(started, PoolCheckoutOutcome.ACQUIRED)
                return connection

        self.pool_class = ObservedQueuePool

    def _observe(self, started: float, outcome: PoolCheckoutOutcome) -> None:
        duration = monotonic() - started
        with self._lock:
            self._telemetry.observe_checkout(duration, outcome)

    def render(self, engine: Engine) -> str:
        if self.pool_class is None:
            return ""
        pool = engine.pool
        if not isinstance(pool, self.pool_class):
            raise ValueError("pool meter does not own this engine pool")
        with self._lock:
            # Read current pool state, not checkin-event counters: checkin fires
            # before return, and detached/invalidated connections need no guesses.
            self._telemetry.set_checked_out(pool.checkedout())
            return self._registry.render_prometheus()

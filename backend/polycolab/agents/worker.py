"""Private built-in worker process entrypoint; it has no HTTP listener."""

from __future__ import annotations

import logging
import signal
import time

from polycolab.agents.runtime.gateways import HttpModelGateway, HttpToolGateway
from polycolab.agents.runtime.remote import ApiBackedWorker, HttpRuntimeGateway
from polycolab.platform.config import WorkerSettings

logger = logging.getLogger(__name__)


def build_worker() -> ApiBackedWorker:
    settings = WorkerSettings()
    return ApiBackedWorker(
        worker_id=settings.runtime_worker_id,
        runtime_gateway=HttpRuntimeGateway(
            settings.runtime_internal_api_url,
            token=settings.runtime_worker_secret,
            timeout_seconds=settings.gateway_request_timeout_seconds,
            max_request_bytes=settings.runtime_api_max_request_bytes,
            max_response_bytes=settings.runtime_api_max_response_bytes,
        ),
        model_gateway=HttpModelGateway(
            settings.runtime_internal_api_url,
            timeout_seconds=settings.gateway_request_timeout_seconds,
            max_response_bytes=settings.gateway_max_response_bytes,
            max_content_bytes=settings.gateway_max_response_bytes,
        ),
        tool_gateway=HttpToolGateway(
            settings.runtime_internal_api_url,
            timeout_seconds=settings.gateway_request_timeout_seconds,
        ),
    )


def main() -> None:
    settings = WorkerSettings()
    worker = build_worker()
    stopping = False

    def stop(_: int, __: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopping:
        try:
            handled = worker.run_once()
        except Exception:
            # Private API outages are ordinary operational failures. Keep the
            # worker alive so a later poll can resume after service recovery.
            logger.exception("built-in worker poll failed; retrying")
            handled = False
        if not handled:
            time.sleep(settings.runtime_worker_poll_seconds)


if __name__ == "__main__":
    main()

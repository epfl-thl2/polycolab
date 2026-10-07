"""Structured, request-correlated logging configuration."""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any

import structlog

from polycolab.platform.config import Settings

_SECRET = re.compile(r"(?i)(authorization|api[_-]?key|token|secret|credential|password)")
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_PROVIDER_KEY = re.compile(r"\b(?:sk|key)-[A-Za-z0-9_-]{6,}\b")


def redact_secrets(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove credentials recursively before any renderer or event sink sees them."""

    def scrub(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if _SECRET.search(str(key)) else scrub(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, tuple):
            return tuple(scrub(item) for item in value)
        if isinstance(value, str):
            return _PROVIDER_KEY.sub("[REDACTED]", _BEARER_VALUE.sub("Bearer [REDACTED]", value))
        return value

    scrubbed = scrub(event)
    assert isinstance(scrubbed, MutableMapping)
    return scrubbed


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(format="%(message)s", level=settings.log_level.upper(), force=True)
    renderer: structlog.types.Processor
    if settings.use_json_logs:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # Run after exception rendering so credentials embedded in exception
            # messages cannot bypass the recursive scrubber.
            redact_secrets,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(settings.log_level.upper()),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

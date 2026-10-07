"""Stable ASGI entrypoint for deployment commands."""

from polycolab.app.application import app as app
from polycolab.app.application import create_app as create_app

__all__ = ["app", "create_app"]

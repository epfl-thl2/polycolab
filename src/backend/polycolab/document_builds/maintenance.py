"""Recover abandoned builds and collect expired private build bytes."""

import logging
from collections.abc import Callable
from threading import Event

from sqlalchemy.orm import Session

from polycolab.artifacts.storage import ArtifactStorage
from polycolab.db.stores.document_builds import SqlBuildStore
from polycolab.db.transaction import SqlAlchemyTransaction
from polycolab.document_builds.service import BuildService
from polycolab.entities.document_builds import BuildLimits
from polycolab.platform.config import Settings


def consume(
    factory: Callable[[], Session], storage: ArtifactStorage, settings: Settings, stopped: Event
) -> None:
    limits = BuildLimits(
        settings.latex_capacity,
        settings.latex_project_queue,
        settings.latex_project_max_bytes,
        settings.latex_execution_seconds,
        settings.latex_queue_seconds,
        settings.latex_retention_days,
    )
    while not stopped.is_set():
        try:
            with factory() as session:
                BuildService(
                    SqlAlchemyTransaction(session),
                    SqlBuildStore(session),
                    storage,
                    settings.latex_image,
                    limits,
                ).cleanup()
        except Exception:
            logging.getLogger(__name__).warning("Document build maintenance failed")
        stopped.wait(5)

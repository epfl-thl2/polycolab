"""FastAPI route composition for the Polycolab application service.

Capability packages compose their local routes. The public ``router`` is the
single JSON API boundary consumed by the application factory.
"""

from fastapi import APIRouter

from polycolab.accounts.routes.router import router as accounts_router
from polycolab.agents.routes.router import router as agents_router
from polycolab.app.configuration import router as configuration_router
from polycolab.artifacts.routes.router import router as artifacts_router
from polycolab.chat.routes.router import router as chat_router
from polycolab.document_builds.routes.router import router as document_builds_router
from polycolab.model_gateway.routes.router import router as model_gateway_router
from polycolab.operations.routes.router import router as operations_router
from polycolab.projects.routes.router import router as projects_router

router = APIRouter()
router.include_router(document_builds_router)
router.include_router(configuration_router)
router.include_router(chat_router)
router.include_router(accounts_router)
router.include_router(artifacts_router)
router.include_router(agents_router)
router.include_router(projects_router)
router.include_router(model_gateway_router)
router.include_router(operations_router)

__all__ = ["router"]

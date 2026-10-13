"""FastAPI route composition for the Polycolab application service.

Capability packages compose their local routes. The public ``router`` is the
single JSON API boundary consumed by the application factory.
"""

from fastapi import APIRouter

from polycolab.accounts.routes.router import router as accounts_router
from polycolab.agents.routes.router import router as agents_router
from polycolab.app.configuration import router as configuration_router
from polycolab.artifacts.routes.router import router as artifacts_router
from polycolab.catalogue.routes.router import router as catalogue_router
from polycolab.execution.routes.router import router as execution_router
from polycolab.model_gateway.routes.router import router as model_gateway_router
from polycolab.operations.routes.router import router as operations_router
from polycolab.projects.routes.router import router as projects_router
from polycolab.research.routes.router import router as research_router
from polycolab.verification.routes.router import router as verification_router

router = APIRouter()
router.include_router(configuration_router)
router.include_router(accounts_router)
router.include_router(artifacts_router)
router.include_router(catalogue_router)
router.include_router(execution_router)
router.include_router(agents_router)
router.include_router(research_router)
router.include_router(projects_router)
router.include_router(model_gateway_router)
router.include_router(operations_router)
router.include_router(verification_router)

__all__ = ["router"]

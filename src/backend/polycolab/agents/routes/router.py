from fastapi import APIRouter

from polycolab.agents.routes.capabilities import router as capabilities_router
from polycolab.agents.routes.hosted_artifacts import router as hosted_artifacts_router
from polycolab.agents.routes.identities import router as identities_router
from polycolab.agents.routes.keys import router as keys_router
from polycolab.agents.routes.proposals import router as proposals_router
from polycolab.agents.routes.repository import router as repository_router
from polycolab.agents.routes.runtime import router as runtime_router
from polycolab.agents.routes.sessions import router as sessions_router
from polycolab.agents.routes.tools import router as tools_router

router = APIRouter()
router.include_router(repository_router)
router.include_router(capabilities_router)
router.include_router(identities_router)
router.include_router(keys_router)
router.include_router(sessions_router)
router.include_router(tools_router)
router.include_router(proposals_router)
router.include_router(runtime_router)

__all__ = ["router"]


router.include_router(hosted_artifacts_router)

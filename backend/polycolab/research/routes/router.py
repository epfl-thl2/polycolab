from fastapi import APIRouter

from polycolab.research.routes.activity import router as activity_router
from polycolab.research.routes.assurance import router as assurance_router
from polycolab.research.routes.core import router as core_router
from polycolab.research.routes.direct import router as direct_router
from polycolab.research.routes.history import router as history_router
from polycolab.research.routes.records import router as records_router
from polycolab.research.routes.reviews import router as reviews_router

router = APIRouter()
router.include_router(reviews_router)
router.include_router(history_router)
router.include_router(core_router)
router.include_router(direct_router)
router.include_router(assurance_router)
router.include_router(records_router)
router.include_router(activity_router)

__all__ = ["router"]

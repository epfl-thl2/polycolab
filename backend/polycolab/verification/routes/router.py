from fastapi import APIRouter

from polycolab.verification.routes.verification import environment_router
from polycolab.verification.routes.verification import router as jobs_router

router = APIRouter()
router.include_router(jobs_router)
router.include_router(environment_router)

__all__ = ["router"]

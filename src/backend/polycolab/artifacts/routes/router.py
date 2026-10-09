from fastapi import APIRouter

from polycolab.artifacts.routes.shared import router as shared_router

router = APIRouter()
router.include_router(shared_router)

__all__ = ["router"]

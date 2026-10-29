from fastapi import APIRouter

from polycolab.artifacts.routes.private import router as private_router

router = APIRouter()
router.include_router(private_router)

__all__ = ["router"]

from fastapi import APIRouter

from polycolab.accounts.routes.auth import router as auth_router
from polycolab.accounts.routes.recovery import router as recovery_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(recovery_router)

__all__ = ["router"]

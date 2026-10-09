from fastapi import APIRouter

from polycolab.workspaces.routes.copies import router as copies_router
from polycolab.workspaces.routes.references import router as references_router
from polycolab.workspaces.routes.repository import router as repository_router
from polycolab.workspaces.routes.tasks import router as tasks_router
from polycolab.workspaces.routes.workspace import router as workspace_router

router = APIRouter()
router.include_router(tasks_router)
router.include_router(repository_router)
router.include_router(workspace_router)
router.include_router(references_router)
router.include_router(copies_router)

__all__ = ["router"]

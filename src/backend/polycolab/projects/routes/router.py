from fastapi import APIRouter

from polycolab.projects.routes.copies import router as copies_router
from polycolab.projects.routes.linear import router as linear_router
from polycolab.projects.routes.project import router as project_router
from polycolab.projects.routes.references import router as references_router
from polycolab.projects.routes.repository import router as repository_router
from polycolab.projects.routes.tasks import router as tasks_router
from polycolab.projects.routes.worktrees import router as worktrees_router

router = APIRouter()
router.include_router(linear_router)
router.include_router(worktrees_router)
router.include_router(tasks_router)
router.include_router(repository_router)
router.include_router(project_router)
router.include_router(references_router)
router.include_router(copies_router)

__all__ = ["router"]

from fastapi import APIRouter

from polycolab.projects.routes.basic_files import router as basic_files_router
from polycolab.projects.routes.collaborative import router as collaborative_router
from polycolab.projects.routes.directory import router as directory_router
from polycolab.projects.routes.project import router as project_router
from polycolab.projects.routes.repository import router as repository_router
from polycolab.projects.routes.worktrees import router as worktrees_router

router = APIRouter()
router.include_router(directory_router)
router.include_router(basic_files_router)
router.include_router(collaborative_router)
router.include_router(worktrees_router)
router.include_router(repository_router)
router.include_router(project_router)

__all__ = ["router"]

from fastapi import APIRouter

from polycolab.catalogue.routes.catalogue import router as catalogue_router
from polycolab.catalogue.routes.community import router as community_router
from polycolab.catalogue.routes.discovery import router as discovery_router
from polycolab.catalogue.routes.publication import router as publication_router

router = APIRouter()
router.include_router(catalogue_router)
router.include_router(community_router)
router.include_router(discovery_router)
router.include_router(publication_router)

__all__ = ["router"]

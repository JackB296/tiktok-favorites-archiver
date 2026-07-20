"""Combined mount point for independently owned feature API routers."""
from fastapi import APIRouter

from server.annotations_api import router as annotations_router
from server.channels_api import router as channels_router
from server.duplicates_api import router as duplicates_router
from server.vibes_api import router as vibes_router


router = APIRouter(prefix="/api")
router.include_router(annotations_router)
router.include_router(vibes_router)
router.include_router(duplicates_router)
router.include_router(channels_router)

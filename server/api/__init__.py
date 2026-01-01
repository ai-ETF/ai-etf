from fastapi import APIRouter

from . import ask, upload, test

router = APIRouter()
router.include_router(ask.router, prefix="/ask")
router.include_router(upload.router, prefix="/upload")
router.include_router(test.router, prefix="/test")

__all__ = ["ask", "upload", "test", "router"]
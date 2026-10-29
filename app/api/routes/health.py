
from fastapi import APIRouter

from app.core.config import settings


router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": settings.app_name,
        "message": f"{settings.app_name} is running",
    }

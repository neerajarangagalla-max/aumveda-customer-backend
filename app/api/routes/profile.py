import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.schemas.profile import ProfileUpdate
from app.services.profile_service import get_profile, update_profile

router = APIRouter(prefix="/profile", tags=["Profile"])
logger = logging.getLogger(__name__)


@router.get("")
async def profile(user=Depends(get_current_user)):
    try:
        data = get_profile(user.id)
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Profile retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve profile.",
        )


@router.patch("")
async def update(payload: ProfileUpdate, user=Depends(get_current_user)):
    try:
        data = update_profile(user.id, payload.model_dump())
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Profile update failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to update profile.",
        )

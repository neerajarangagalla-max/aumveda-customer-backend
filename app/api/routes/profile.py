
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.core.supabase import supabase_admin
from app.schemas.profile import ProfileUpdate

router = APIRouter(prefix="/profile", tags=["Profile"])
logger = logging.getLogger(__name__)


def _get_profile(user_id: str):
    response = (
        supabase_admin.table("profiles")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )

    data = response.data or []
    return data[0] if data else None


def _update_profile(user_id: str, payload: dict):
    clean_payload = {
        key: value
        for key, value in payload.items()
        if value is not None
    }

    if not clean_payload:
        return _get_profile(user_id)

    response = (
        supabase_admin.table("profiles")
        .update(clean_payload)
        .eq("id", user_id)
        .execute()
    )

    data = response.data or []
    return data[0] if data else _get_profile(user_id)


@router.get("")
async def profile(user=Depends(get_current_user)):
    try:
        data = _get_profile(user.id)

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="Profile not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Profile retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve profile.",
        )



@router.patch("")
async def update(
    payload: ProfileUpdate,
    user=Depends(get_current_user),
):
    try:
        update_data = payload.model_dump(exclude_unset=True)

        # Keep both name fields consistent when either is provided.
        if "name" in update_data:
            update_data["full_name"] = update_data.pop("name")

        data = _update_profile(user.id, update_data)

        if data is None:
            raise HTTPException(
                status_code=404,
                detail="Profile not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Profile update failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to update profile.",
        )

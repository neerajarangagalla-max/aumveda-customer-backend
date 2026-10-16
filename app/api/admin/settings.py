from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/settings",
    tags=["Admin Settings"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("")
def list_site_settings():
    try:
        result = supabase.table("site_settings").select("*").execute()

        items = result.data or []
        return {
            "items": items,
            "total": len(items),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to retrieve site settings; "
                "verify the site_settings table exists"
            ),
        ) from exc

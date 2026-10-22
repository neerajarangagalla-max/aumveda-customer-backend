
import logging

from fastapi import APIRouter, HTTPException

from app.core.supabase import supabase_admin

router = APIRouter(
    prefix="/categories",
    tags=["Categories"],
)

logger = logging.getLogger(__name__)

CATEGORY_FIELDS = """
    id,
    name,
    slug,
    description,
    image_url,
    is_active,
    home_sort_order
"""


@router.get("")
async def categories():
    try:
        response = (
            supabase_admin
            .table("categories")
            .select(CATEGORY_FIELDS)
            .eq("is_active", True)
            .order("home_sort_order")
            .execute()
        )

        data = response.data or []

        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }

    except Exception:
        logger.exception("Category list failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve categories.",
        )


@router.get("/{slug}")
async def category(slug: str):
    try:
        response = (
            supabase_admin
            .table("categories")
            .select(CATEGORY_FIELDS)
            .eq("slug", slug)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

        data = response.data or []

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Category not found.",
            )

        return {
            "status": "success",
            "data": data[0],
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Category lookup failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category.",
        )

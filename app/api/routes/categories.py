
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
    parent_id,
    name,
    slug,
    description,
    image_url,
    is_active,
    home_sort_order,
    sort_order
"""


@router.get("")
async def categories():
    try:
        # Fetch active categories.
        response = (
            supabase_admin
            .table("categories")
            .select(CATEGORY_FIELDS)
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )

        all_categories = response.data or []

        # Separate parent categories and subcategories.
        subcategories_by_parent = {}

        for item in all_categories:
            parent_id = item.get("parent_id")

            if parent_id:
                subcategories_by_parent.setdefault(
                    str(parent_id), []
                ).append(item)

        parents = []

        for item in all_categories:
            if item.get("parent_id") is not None:
                continue

            category = {
                **item,
                "subcategories": subcategories_by_parent.get(
                    str(item["id"]), []
                ),
            }

            parents.append(category)

        return {
            "status": "success",
            "count": len(parents),
            "data": parents,
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

        selected_category = data[0]

        children_response = (
            supabase_admin
            .table("categories")
            .select(CATEGORY_FIELDS)
            .eq("parent_id", selected_category["id"])
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )

        selected_category["subcategories"] = (
            children_response.data or []
        )

        return {
            "status": "success",
            "data": selected_category,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Category lookup failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve category.",
        )

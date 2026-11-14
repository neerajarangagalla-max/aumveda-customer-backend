from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/reviews",
    tags=["Admin Reviews"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("")
def list_reviews(
    product_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("product_reviews").select("*", count="exact")

        if product_id:
            query = query.eq("product_id", product_id)

        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        return {
            "items": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve product reviews",
        ) from exc


@router.get("/{review_id}")
def get_review(review_id: str):
    try:
        result = (
            supabase.table("product_reviews")
            .select("*")
            .eq("id", review_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Review not found")

        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve review",
        ) from exc


@router.delete("/{review_id}")
def delete_review(review_id: str):
    try:
        result = (
            supabase.table("product_reviews")
            .delete()
            .eq("id", review_id)
            .select("id")
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Review not found")

        return {
            "message": "Review deleted",
            "id": result.data[0]["id"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to delete review",
        ) from exc

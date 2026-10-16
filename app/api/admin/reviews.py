from typing import Literal

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
    status_filter: str | None = Query(default=None, alias="status"),
    product_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("product_reviews").select("*", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)

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


@router.patch("/{review_id}/status")
def update_review_status(
    review_id: str,
    new_status: Literal["pending", "approved", "rejected"],
):
    try:
        existing = (
            supabase.table("product_reviews")
            .select("id")
            .eq("id", review_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(status_code=404, detail="Review not found")

        result = (
            supabase.table("product_reviews")
            .update({"status": new_status})
            .eq("id", review_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Review status was not updated",
            )

        return {
            "message": "Review status updated",
            "review": result.data[0],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update review status; verify the review schema and allowed statuses",
        ) from exc

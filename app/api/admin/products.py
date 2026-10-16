from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/products",
    tags=["Admin Products"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("")
def list_products(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("products").select("*", count="exact")
        if status_filter:
            query = query.eq("status", status_filter)
        if search:
            query = query.ilike("name", f"%{search}%")

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
        raise HTTPException(500, "Unable to retrieve products") from exc


@router.get("/{product_id}")
def get_product(product_id: str):
    try:
        result = (
            supabase.table("products")
            .select("*, product_images(*), product_variants(*)")
            .eq("id", product_id)
            .maybe_single()
            .execute()
        )
        if not result.data:
            raise HTTPException(404, "Product not found")
        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Unable to retrieve product") from exc


@router.patch("/{product_id}/status")
def update_product_status(
    product_id: str,
    new_status: Literal["draft", "pending", "active", "rejected", "archived"],
):
    try:
        existing = (
            supabase.table("products")
            .select("id")
            .eq("id", product_id)
            .maybe_single()
            .execute()
        )
        if not existing.data:
            raise HTTPException(404, "Product not found")

        result = (
            supabase.table("products")
            .update({"status": new_status})
            .eq("id", product_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(500, "Product status was not updated")
        return {"message": "Product status updated", "product": result.data[0]}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, "Unable to update product status") from exc

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/inventory",
    tags=["Admin Inventory"],
    dependencies=[Depends(get_current_admin)],
)


@router.get("/transactions")
def list_inventory_transactions(
    product_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("inventory_transactions").select(
            "*", count="exact"
        )

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
            detail="Unable to retrieve inventory transactions",
        ) from exc


@router.get("/transactions/{transaction_id}")
def get_inventory_transaction(transaction_id: str):
    try:
        result = (
            supabase.table("inventory_transactions")
            .select("*")
            .eq("id", transaction_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Inventory transaction not found",
            )

        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve inventory transaction",
        ) from exc

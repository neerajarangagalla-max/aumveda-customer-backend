from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin Orders"],
    dependencies=[Depends(get_current_admin)],
)


class OrderStatusUpdate(BaseModel):
    status: Literal[
        "pending",
        "confirmed",
        "processing",
        "shipped",
        "delivered",
        "cancelled",
        "returned",
    ]


@router.get("")
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("orders").select("*", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)
        if search and search.strip():
            query = query.ilike("order_number", f"%{search.strip()}%")
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
            detail="Unable to retrieve orders",
        ) from exc


@router.get("/{order_id}")
def get_order(order_id: str):
    try:
        result = (
            supabase.table("orders")
            .select("*, order_items(*)")
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Order not found")

        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve order",
        ) from exc




@router.patch("/{order_id}/status")
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    current_admin=Depends(get_current_admin),
):
    try:
        existing = (
            supabase.table("orders")
            .select("id, status")
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        previous_status = existing.data["status"]
        new_status = payload.status

        if previous_status == new_status:
            return {
                "message": "Order status is unchanged",
                "order": existing.data,
            }

        result = (
            supabase.table("orders")
            .update({"status": new_status})
            .eq("id", order_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Order status was not updated",
            )

        updated_order = result.data[0]

        try:
            supabase.table("order_status_history").insert({
                "order_id": order_id,
                "status": new_status,
                "changed_by": str(current_admin.id),
                "notes": (
                    f"Status changed from {previous_status} "
                    f"to {new_status} by admin"
                ),
            }).execute()

        except Exception as history_error:
            try:
                supabase.table("orders").update({
                    "status": previous_status,
                }).eq("id", order_id).execute()
            except Exception:
                pass

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to record order status history. "
                    "The status rollback was attempted."
                ),
            ) from history_error

        return {
            "message": "Order status updated and history recorded",
            "order": updated_order,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update order status",
        ) from exc

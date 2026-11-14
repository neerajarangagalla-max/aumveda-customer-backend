from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from app.core.supabase import supabase
from app.core.security import get_current_admin

router = APIRouter(
    prefix="/admin/customers",
    tags=["Admin Customers"],
    dependencies=[Depends(get_current_admin)],
)


class CustomerUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)


@router.get("")
def list_customers(
    search: str | None = None,
    active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = (
            supabase.table("profiles")
            .select("*", count="exact")
            .eq("role", "customer")
        )

        if active is not None:
            query = query.eq("is_active", active)

        if search:
            safe_search = search.strip().replace(",", "").replace("(", "").replace(")", "")
            query = query.or_(
                f"full_name.ilike.%{safe_search}%,email.ilike.%{safe_search}%,phone.ilike.%{safe_search}%"
                )

        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        customers = result.data or []
        customer_ids = [
            str(customer["id"])
            for customer in customers
            if customer.get("id")
        ]
        orders_by_customer = {}

        if customer_ids:
            orders_result = (
                supabase.table("orders")
                .select("customer_id, total_amount, created_at")
                .in_("customer_id", customer_ids)
                .execute()
            )

            for order in orders_result.data or []:
                customer_id = str(order.get("customer_id"))
                summary = orders_by_customer.setdefault(
                    customer_id,
                    {
                        "order_count": 0,
                        "total_spent": 0.0,
                        "last_order_at": None,
                    },
                )
                summary["order_count"] += 1
                summary["total_spent"] += float(
                    order.get("total_amount") or 0
                )

                created_at = order.get("created_at")
                if created_at and (
                    not summary["last_order_at"]
                    or created_at > summary["last_order_at"]
                ):
                    summary["last_order_at"] = created_at

        for customer in customers:
            customer.update(
                orders_by_customer.get(
                    str(customer.get("id")),
                    {
                        "order_count": 0,
                        "total_spent": 0.0,
                        "last_order_at": None,
                    },
                )
            )

        month_start = datetime.now(timezone.utc).replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat()
        total_customers = (
            supabase.table("profiles")
            .select("id", count="exact")
            .eq("role", "customer")
            .execute()
        )
        active_customers = (
            supabase.table("profiles")
            .select("id", count="exact")
            .eq("role", "customer")
            .eq("is_active", True)
            .execute()
        )
        new_customers = (
            supabase.table("profiles")
            .select("id", count="exact")
            .eq("role", "customer")
            .gte("created_at", month_start)
            .execute()
        )

        return {
            "items": customers,
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
            "summary": {
                "total_customers": total_customers.count or 0,
                "active_customers": active_customers.count or 0,
                "new_this_month": new_customers.count or 0,
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve customers",
        ) from exc


@router.get("/{customer_id}")
def get_customer(customer_id: str):
    try:
        result = (
            supabase.table("profiles")
            .select("*")
            .eq("id", customer_id)
            .eq("role", "customer")
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Customer not found")

        return result.data
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve customer",
        ) from exc


@router.patch("/{customer_id}")
def update_customer(customer_id: str, payload: CustomerUpdate):
    updates = {}

    if "full_name" in payload.model_fields_set:
        full_name = (payload.full_name or "").strip()
        if not full_name:
            raise HTTPException(
                status_code=422,
                detail="Customer name cannot be empty",
            )
        updates["full_name"] = full_name

    if "phone" in payload.model_fields_set:
        updates["phone"] = (payload.phone or "").strip() or None

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one customer field to update",
        )

    try:
        result = (
            supabase.table("profiles")
            .update(updates)
            .eq("id", customer_id)
            .eq("role", "customer")
            .select("*")
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Customer not found")

        return {
            "message": "Customer profile updated",
            "customer": result.data[0],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update customer profile",
        ) from exc


@router.patch("/{customer_id}/active")
def set_customer_active(customer_id: str, is_active: bool):
    try:
        existing = (
            supabase.table("profiles")
            .select("id")
            .eq("id", customer_id)
            .eq("role", "customer")
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(status_code=404, detail="Customer not found")

        result = (
            supabase.table("profiles")
            .update({"is_active": is_active})
            .eq("id", customer_id)
            .eq("role", "customer")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=500,
                detail="Customer status was not updated",
            )

        return {
            "message": "Customer account status updated",
            "customer": result.data[0],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update customer account",
        ) from exc

from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.supabase import supabase
from app.core.security import get_current_admin

router = APIRouter(
    prefix="/admin/customers",
    tags=["Admin Customers"],
    dependencies=[Depends(get_current_admin)],
)


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

        return {
            "items": result.data or [],
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
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

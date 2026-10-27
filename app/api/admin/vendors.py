
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase

router = APIRouter(
    prefix="/admin/vendors",
    tags=["Admin Vendors"],
    dependencies=[Depends(get_current_admin)],
)

VendorStatus = Literal[
    "approved",
    "rejected",
    "suspended",
    "pending",
]


def database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "invalid input syntax" in message:
        return HTTPException(400, "Invalid vendor ID or input")

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(409, "A conflicting vendor record exists")

    return HTTPException(500, "Vendor operation failed")


@router.get("")
def list_vendors(
    status_filter: VendorStatus | None = Query(
        default=None,
        alias="status",
    ),
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("vendors").select("*", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)

        if search and search.strip():
            # Keep the filter safe for PostgREST's OR expression.
            term = (
                search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
                .replace(",", "")
                .replace("(", "")
                .replace(")", "")
            )

            if term:
                query = query.or_(
                    f"business_name.ilike.%{term}%,"
                    f"legal_name.ilike.%{term}%,"
                    f"email.ilike.%{term}%"
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
            500,
            "Unable to retrieve vendors",
        ) from exc


@router.get("/{vendor_id}")
def get_vendor(vendor_id: UUID):
    try:
        result = (
            supabase.table("vendors")
            .select("*")
            .eq("id", str(vendor_id))
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(404, "Vendor not found")

        return result.data

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc


@router.patch("/{vendor_id}/status")
def update_vendor_status(
    vendor_id: UUID,
    new_status: VendorStatus,
):
    try:
        vendor_id = str(vendor_id)

        existing = (
            supabase.table("vendors")
            .select("id")
            .eq("id", vendor_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(404, "Vendor not found")

        result = (
            supabase.table("vendors")
            .update({"status": new_status})
            .eq("id", vendor_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                500,
                "Vendor status was not updated",
            )

        return {
            "message": "Vendor status updated successfully",
            "vendor": result.data[0],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc


@router.patch("/{vendor_id}/active")
def update_vendor_active_status(
    vendor_id: UUID,
    is_active: bool,
):
    try:
        vendor_id = str(vendor_id)

        existing = (
            supabase.table("vendors")
            .select("id")
            .eq("id", vendor_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(404, "Vendor not found")

        result = (
            supabase.table("vendors")
            .update({"is_active": is_active})
            .eq("id", vendor_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                500,
                "Vendor account status was not updated",
            )

        return {
            "message": "Vendor account status updated successfully",
            "vendor": result.data[0],
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise database_error(exc) from exc

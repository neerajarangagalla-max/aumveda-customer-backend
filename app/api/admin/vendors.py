import logging
import re
import secrets
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase, supabase_admin

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

logger = logging.getLogger(__name__)


class CreateVendorRequest(BaseModel):
    business_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone: str = Field(..., min_length=5, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    legal_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="India", max_length=100)
    commission_rate: float = Field(
        default=0,
        ge=0,
        le=100,
    )


def generate_vendor_slug(business_name: str) -> str:
    base_slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        business_name.lower().strip(),
    ).strip("-")
    return f"{base_slug}-{secrets.token_hex(4)}"


def rollback_vendor_creation(
    vendor_id: str | None,
    auth_user_id: str | None,
) -> None:
    if vendor_id and auth_user_id:
        try:
            (
                supabase_admin.table("vendor_members")
                .delete()
                .eq("vendor_id", vendor_id)
                .eq("user_id", auth_user_id)
                .execute()
            )
        except Exception:
            logger.exception("Failed to remove vendor membership during rollback")

    if vendor_id:
        try:
            (
                supabase_admin.table("vendors")
                .delete()
                .eq("id", vendor_id)
                .execute()
            )
        except Exception:
            logger.exception("Failed to remove vendor during rollback")

    if auth_user_id:
        try:
            supabase_admin.auth.admin.delete_user(auth_user_id)
        except Exception:
            logger.exception("Failed to remove Auth user during rollback")


def database_error(exc: Exception) -> HTTPException:
    message = str(exc).lower()

    if "invalid input syntax" in message:
        return HTTPException(400, "Invalid vendor ID or input")

    if "duplicate key" in message or "unique constraint" in message:
        return HTTPException(409, "A conflicting vendor record exists")

    return HTTPException(500, "Vendor operation failed")


@router.post("/create")
def create_vendor(
    payload: CreateVendorRequest,
    current_admin=Depends(get_current_admin),
):
    vendor_id = None
    auth_user_id = None
    try:
        email = str(payload.email).lower().strip()
        existing_vendor = (
            supabase_admin.table("vendors")
            .select("id")
            .eq("email", email)
            .limit(1)
            .execute()
            )
        if existing_vendor and existing_vendor.data:
            raise HTTPException(
                status_code=409,
                detail="A vendor with this email already exists.",
                )

        password = payload.password
        try:
            auth_response = supabase_admin.auth.admin.create_user(
                {
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {
                        "role": "vendor",
                        "full_name": payload.business_name.strip(),
                    },
                }
            )
        except Exception as exc:
            error_message = str(exc).lower()
            if (
                "already registered" in error_message
                or "already exists" in error_message
                or "duplicate key" in error_message
                or "unique constraint" in error_message
            ):
                raise HTTPException(
                    status_code=409,
                    detail="An account with this email already exists.",
                ) from exc
            raise

        auth_user = getattr(auth_response, "user", None)
        if not auth_user:
            raise HTTPException(
                status_code=500,
                detail="Unable to create the vendor account.",
            )
        auth_user_id = str(auth_user.id)

        profile_result = (
            supabase_admin.table("profiles")
            .update(
                {
                    "role": "vendor",
                    "full_name": payload.business_name.strip(),
                }
            )
            .eq("id", auth_user_id)
            .select("id")
            .execute()
        )
        if not profile_result.data:
            raise HTTPException(
                status_code=500,
                detail="Unable to set up the vendor profile.",
            )

        vendor_data = payload.model_dump(exclude={"password"}, exclude_none=True)
        vendor_data.update(
            {
                "email": email,
                "status": "approved",
                "slug": generate_vendor_slug(payload.business_name),
            }
        )
        vendor_result = (
            supabase_admin.table("vendors")
            .insert(vendor_data)
            .select("*")
            .execute()
        )
        if not vendor_result.data:
            raise HTTPException(
                status_code=500,
                detail="Unable to create the vendor record.",
            )

        vendor_record = vendor_result.data[0]
        vendor_id = str(vendor_record["id"])
        membership_result = (
            supabase_admin.table("vendor_members")
            .insert(
                {
                    "user_id": auth_user_id,
                    "vendor_id": vendor_id,
                    "member_role": "owner",
                    "is_active": True,
                    "permission_mode": "legacy",
                    }
            )
            .select("vendor_id")
            .execute()
        )
        if not membership_result.data:
            raise HTTPException(
                status_code=500,
                detail="Unable to link the vendor account.",
            )

        return {
            "message": "Vendor created successfully.",
            "vendor": vendor_record,
        }

    except Exception as exc:
        logger.exception("CREATE VENDOR FAILED")
    if auth_user_id:
        rollback_vendor_creation(vendor_id, auth_user_id)
    raise database_error(exc) from exc


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

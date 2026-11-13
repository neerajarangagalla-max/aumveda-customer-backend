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
    created_auth_user = False

    try:
        email = str(payload.email).lower().strip()

        # ---------------------------------------------------------
        # 1. Check whether this email already belongs to a vendor
        # ---------------------------------------------------------
        existing_vendor = (
            supabase_admin.table("vendors")
            .select("id")
            .eq("email", email)
            .limit(1)
            .execute()
        )

        if existing_vendor.data:
            raise HTTPException(
                status_code=409,
                detail="A vendor with this email already exists.",
            )

        # ---------------------------------------------------------
        # 2. Find an existing Supabase Auth user
        # ---------------------------------------------------------
        existing_auth_user = None

        try:
            page = 1
            per_page = 1000

            while True:
                users_response = (
                    supabase_admin.auth.admin.list_users(
                        page=page,
                        per_page=per_page,
                    )
                )

                if isinstance(users_response, list):
                    users = users_response
                else:
                    users = getattr(users_response, "users", None) or []

                for user in users:
                    user_email = (
                        getattr(user, "email", None) or ""
                    ).lower().strip()

                    if user_email == email:
                        existing_auth_user = user
                        break

                if existing_auth_user or len(users) < per_page:
                    break

                page += 1

        except Exception as exc:
            logger.exception(
                "Failed to search existing Auth users"
            )

            raise HTTPException(
                status_code=500,
                detail="Unable to verify the existing account.",
            ) from exc

        # ---------------------------------------------------------
        # 3. Reuse existing Auth user
        # ---------------------------------------------------------
        if existing_auth_user:
            auth_user_id = str(existing_auth_user.id)

        # ---------------------------------------------------------
        # 4. Create a new Auth user only if one does not exist
        # ---------------------------------------------------------
        else:
            try:
                auth_response = (
                    supabase_admin.auth.admin.create_user(
                        {
                            "email": email,
                            "password": payload.password,
                            "email_confirm": True,
                            "user_metadata": {
                                "role": "vendor",
                                "full_name": (
                                    payload.business_name.strip()
                                ),
                            },
                        }
                    )
                )

                auth_user = getattr(
                    auth_response,
                    "user",
                    None,
                )

                if not auth_user:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Unable to create the vendor account."
                        ),
                    )

                auth_user_id = str(auth_user.id)
                created_auth_user = True

            except Exception as exc:
                error_message = str(exc).lower()

                # -------------------------------------------------
                # Race-condition protection:
                # Another request may have created the Auth user
                # between our lookup and create_user().
                # -------------------------------------------------
                if (
                    "already registered" in error_message
                    or "already exists" in error_message
                    or "duplicate key" in error_message
                    or "unique constraint" in error_message
                ):
                    existing_auth_user = None

                    try:
                        page = 1
                        per_page = 1000

                        while True:
                            users_response = (
                                supabase_admin.auth.admin.list_users(
                                    page=page,
                                    per_page=per_page,
                                )
                            )

                            if isinstance(users_response, list):
                                users = users_response
                            else:
                                users = getattr(users_response, "users", None) or []

                            for user in users:
                                user_email = (
                                    getattr(
                                        user,
                                        "email",
                                        None,
                                    )
                                    or ""
                                ).lower().strip()

                                if user_email == email:
                                    existing_auth_user = user
                                    break

                            if (
                                existing_auth_user
                                or len(users) < per_page
                            ):
                                break

                            page += 1

                    except Exception as lookup_exc:
                        logger.exception(
                            "Failed to find existing Auth user "
                            "after duplicate email error"
                        )

                        raise HTTPException(
                            status_code=500,
                            detail=(
                                "The email already exists, "
                                "but the existing account "
                                "could not be located."
                            ),
                        ) from lookup_exc

                    if existing_auth_user:
                        auth_user_id = str(
                            existing_auth_user.id
                        )
                        created_auth_user = False
                    else:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                "The email already exists in "
                                "Auth, but the existing account "
                                "could not be found."
                            ),
                        ) from exc

                else:
                    raise

        # ---------------------------------------------------------
        # 5. Do NOT change an existing customer's profile role
        #
        # If this is a newly created Auth user, create/update
        # the vendor profile.
        #
        # If this is an existing customer, leave their existing
        # customer profile unchanged.
        # ---------------------------------------------------------
        if created_auth_user:
            profile_result = (
                supabase_admin.table("profiles")
                .update(
                    {
                        "role": "vendor",
                        "full_name": (
                            payload.business_name.strip()
                        ),
                    }
                )
                .eq("id", auth_user_id)
                .select("id")
                .execute()
            )

            if not profile_result.data:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Unable to set up the vendor profile."
                    ),
                )

        # ---------------------------------------------------------
        # 6. Create vendor record
        # ---------------------------------------------------------
        vendor_data = payload.model_dump(
            exclude={"password"},
            exclude_none=True,
        )

        vendor_data.update(
            {
                "email": email,
                "status": "approved",
                "slug": generate_vendor_slug(
                    payload.business_name
                ),
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
                detail=(
                    "Unable to create the vendor record."
                ),
            )

        vendor_record = vendor_result.data[0]
        vendor_id = str(vendor_record["id"])

        # ---------------------------------------------------------
        # 7. Link Auth user to vendor
        # ---------------------------------------------------------
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
                detail=(
                    "Unable to link the vendor account."
                ),
            )

        # ---------------------------------------------------------
        # 8. Success
        # ---------------------------------------------------------
        return {
            "message": "Vendor created successfully.",
            "vendor": vendor_record,
        }

    # -------------------------------------------------------------
    # Preserve intentional HTTP errors
    # -------------------------------------------------------------
    except HTTPException:
        if vendor_id:
            rollback_vendor_creation(
                vendor_id,
                auth_user_id if created_auth_user else None,
            )
        elif created_auth_user and auth_user_id:
            rollback_vendor_creation(
                None,
                auth_user_id,
            )

        raise

    # -------------------------------------------------------------
    # Handle unexpected database/backend errors
    # -------------------------------------------------------------
    except Exception as exc:
        logger.exception("CREATE VENDOR FAILED")

        if vendor_id:
            rollback_vendor_creation(
                vendor_id,
                auth_user_id if created_auth_user else None,
            )
        elif created_auth_user and auth_user_id:
            rollback_vendor_creation(
                None,
                auth_user_id,
            )

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


from typing import Any

from fastapi import (
    Depends,
    Header,
    HTTPException,
    status,
)

from app.core.supabase import (
    supabase_admin,
    supabase_auth,
)


# ============================================================
# AUMVEDA VENDOR AUTHENTICATION
#
# Validates:
#   - Supabase Auth identity
#   - Active profile
#   - Vendor membership
#   - Active vendor business
#   - Membership permission mode
#
# The vendor_id is always derived from the
# authenticated membership, never from user input.
# ============================================================


async def get_current_vendor(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:

    # --------------------------------------------------------
    # 1. ACCESS TOKEN
    # --------------------------------------------------------

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required.",
        )

    scheme, separator, token = authorization.partition(" ")

    if (
        not separator
        or scheme.lower() != "bearer"
        or not token.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid Bearer token is required.",
        )

    token = token.strip()

    # --------------------------------------------------------
    # 2. SUPABASE AUTH IDENTITY
    # --------------------------------------------------------

    try:
        auth_response = supabase_auth.auth.get_user(
            token
        )

        user = auth_response.user

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token.",
            )

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
        )

    user_id = str(user.id)

    # --------------------------------------------------------
    # 3. USER PROFILE
    # --------------------------------------------------------

    try:
        profile_response = (
            supabase_admin
            .table("profiles")
            .select(
                "id, role, full_name, phone, "
                "avatar_url, is_active"
            )
            .eq("id", user_id)
            .limit(1)
            .execute()
        )

        profiles = profile_response.data or []

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify vendor profile.",
        )

    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor profile was not found.",
        )

    profile = profiles[0]

    if profile.get("role") != "vendor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not a vendor account.",
        )

    if profile.get("is_active") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor account is inactive.",
        )

    # --------------------------------------------------------
    # 4. ACTIVE VENDOR MEMBERSHIP
    # --------------------------------------------------------

    try:
        membership_response = (
            supabase_admin
            .table("vendor_members")
            .select(
                "vendor_id, user_id, member_role, "
                "is_active, permission_mode"
            )
            .eq("user_id", user_id)
            .eq("is_active", True)
            .limit(2)
            .execute()
        )

        memberships = membership_response.data or []

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify vendor membership.",
        )

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No active vendor membership was found.",
        )

    # Our current authentication design supports
    # one active vendor business per login.
    #
    # Do not silently choose one if conflicting
    # active memberships ever appear.

    if len(memberships) != 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Multiple active vendor memberships "
                "require account review."
            ),
        )

    membership = memberships[0]

    vendor_id = str(
        membership.get("vendor_id") or ""
    )

    member_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    permission_mode = str(
        membership.get("permission_mode") or ""
    ).strip().lower()

    if member_role not in {
        "owner",
        "manager",
        "staff",
        "inventory",
        "orders",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid vendor membership role.",
        )

    if permission_mode not in {
        "legacy",
        "custom",
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid vendor permission mode.",
        )

    if not vendor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor membership is incomplete.",
        )

    # --------------------------------------------------------
    # 5. VENDOR BUSINESS
    # --------------------------------------------------------

    try:
        vendor_response = (
            supabase_admin
            .table("vendors")
            .select("*")
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        vendors = vendor_response.data or []

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify vendor business.",
        )

    if not vendors:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor business was not found.",
        )

    vendor = vendors[0]

    if vendor.get("is_active") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor business is inactive.",
        )

    return {
        "user": user,
        "user_id": user_id,
        "profile": profile,
        "membership": membership,
        "vendor": vendor,
        "vendor_id": vendor_id,
    }


# ============================================================
# APPROVED VENDOR
# ============================================================

async def get_approved_vendor(
    vendor_context: dict[str, Any] = Depends(
        get_current_vendor
    ),
) -> dict[str, Any]:

    vendor = vendor_context["vendor"]

    vendor_status = str(
        vendor.get("status") or ""
    ).strip().lower()

    if vendor_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Vendor approval is required.",
                "vendor_status": vendor.get("status"),
            },
        )

    return vendor_context


# ============================================================
# VENDOR OWNER
#
# Financial, team and privileged business APIs
# must use this dependency.
# ============================================================

async def get_vendor_owner(
    vendor_context: dict[str, Any] = Depends(
        get_approved_vendor
    ),
) -> dict[str, Any]:

    membership = vendor_context["membership"]

    member_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    if member_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Vendor owner access is required.",
        )

    return vendor_context

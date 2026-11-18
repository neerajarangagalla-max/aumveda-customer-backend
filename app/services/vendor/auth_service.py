
"""
AUMVEDA Vendor Backend
Vendor Registration and Authentication Service

Features:
- Existing Vendor Owner registration
- Shared Vendor Owner / Employee login
- Supabase Auth email/password authentication
- Active profile verification
- Active vendor membership verification
- Vendor business verification
- Owner and staff response separation
- Protection of sensitive business information

Security rules:
- Employees cannot access inactive memberships.
- Staff cannot receive owner-only business fields.
- Multiple active memberships are rejected.
- Staff cannot obtain Owner privileges through login.
- Vendor ID comes from verified database membership.
- Pending invitation accounts cannot log in to Vendor Web.

Staff invitation acceptance and membership activation
are implemented separately.
"""

import logging
import re

from fastapi import HTTPException, status
from supabase import create_client

from app.core.config import settings
from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.auth"
)


# ============================================================
# HELPERS
# ============================================================

def _slugify(value: str) -> str:
    value = value.strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    value = value.strip("-")

    return value or "vendor"


def _database_unavailable(
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail=message,
    )


def _access_denied(
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=message,
    )


def _get_auth_client():
    """
    Use the configured public authentication key
    for email/password login and registration.

    Never use the service-role client for
    password authentication.
    """

    return create_client(
        settings.supabase_url,
        settings.auth_client_key,
    )


# ============================================================
# VENDOR OWNER REGISTRATION
#
# Existing registration behavior is preserved.
# Employee accounts must never use this function.
# ============================================================

def register_vendor(
    payload: dict,
) -> dict:

    email = payload["email"]
    password = payload["password"]

    full_name = payload["full_name"]
    phone = payload.get("phone")

    business_name = payload["business_name"]
    legal_name = payload.get("legal_name")

    business_email = (
        payload.get("business_email")
        or email
    )

    business_phone = (
        payload.get("business_phone")
        or phone
    )

    city = payload.get("city")
    state = payload.get("state")

    country = (
        payload.get("country")
        or "India"
    )

    # --------------------------------------------------------
    # 1. CREATE SUPABASE AUTH ACCOUNT
    # --------------------------------------------------------

    try:
        auth_client = _get_auth_client()

        signup_response = (
            auth_client.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": {
                        "data": {
                            "full_name": full_name,
                            "phone": phone,
                            "role": "vendor",
                        }
                    },
                }
            )
        )

    except Exception as exc:
        logger.exception(
            "Vendor registration authentication failed."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "Unable to register vendor account."
            ),
        ) from exc

    user = signup_response.user

    if not user:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "Unable to create vendor account."
            ),
        )

    user_id = str(user.id)

    # --------------------------------------------------------
    # 2. PROFILE AND BUSINESS PROVISIONING
    # --------------------------------------------------------

    try:
        existing_profile_response = (
            supabase_admin
            .table("profiles")
            .select("id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )

        existing_profiles = (
            existing_profile_response.data or []
        )

        if existing_profiles:
            (
                supabase_admin
                .table("profiles")
                .update({
                    "role": "vendor",
                    "full_name": full_name,
                    "phone": phone,
                    "is_active": True,
                })
                .eq("id", user_id)
                .execute()
            )

        else:
            (
                supabase_admin
                .table("profiles")
                .insert({
                    "id": user_id,
                    "role": "vendor",
                    "full_name": full_name,
                    "phone": phone,
                    "is_active": True,
                })
                .execute()
            )

        # ----------------------------------------------------
        # 3. CREATE VENDOR BUSINESS
        # ----------------------------------------------------

        base_slug = _slugify(
            business_name
        )

        vendor_slug = (
            f"{base_slug}-{user_id[:8]}"
        )

        vendor_response = (
            supabase_admin
            .table("vendors")
            .insert({
                "business_name": business_name,
                "slug": vendor_slug,
                "legal_name": legal_name,
                "email": business_email,
                "phone": business_phone,
                "city": city,
                "state": state,
                "country": country,
                "status": "pending",
                "commission_rate": 0,
                "is_active": True,
            })
            .execute()
        )

        vendors = (
            vendor_response.data or []
        )

        if not vendors:
            raise RuntimeError(
                "Vendor business was not created."
            )

        vendor = vendors[0]

        vendor_id = str(
            vendor["id"]
        )

        # ----------------------------------------------------
        # 4. CREATE VENDOR OWNER MEMBERSHIP
        #
        # Preserve the existing owner setup.
        # ----------------------------------------------------

        (
            supabase_admin
            .table("vendor_members")
            .insert({
                "vendor_id": vendor_id,
                "user_id": user_id,
                "member_role": "owner",
                "is_active": True,
            })
            .execute()
        )

    except Exception as exc:
        logger.exception(
            "Vendor business provisioning failed."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Vendor account was created in "
                "authentication, but business setup "
                "could not be completed. "
                "Contact support before retrying."
            ),
        ) from exc

    return {
        "message": (
            "Vendor registration submitted successfully."
        ),
        "user": {
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": "vendor",
        },
        "vendor": {
            "id": vendor_id,
            "business_name": business_name,
            "status": "pending",
        },
    }


# ============================================================
# SHARED VENDOR / EMPLOYEE LOGIN
#
# POST /api/v1/vendor/auth/login
# ============================================================

def login_vendor(
    email: str,
    password: str,
) -> dict:

    # --------------------------------------------------------
    # 1. AUTHENTICATE WITH SUPABASE AUTH
    # --------------------------------------------------------

    try:
        auth_client = _get_auth_client()

        auth_response = (
            auth_client.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
        )

    except Exception as exc:
        logger.info(
            "Vendor password authentication rejected."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail="Invalid login credentials.",
        ) from exc

    user = auth_response.user
    session = auth_response.session

    if not user or not session:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail="Invalid login credentials.",
        )

    user_id = str(user.id)

    # --------------------------------------------------------
    # 2. LOAD AND VERIFY USER PROFILE
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

        profiles = (
            profile_response.data or []
        )

    except Exception as exc:
        logger.exception(
            "Vendor login profile lookup failed."
        )

        raise _database_unavailable(
            "Unable to verify vendor profile."
        ) from exc

    if not profiles:
        raise _access_denied(
            "Vendor profile was not found."
        )

    profile = profiles[0]

    if profile.get("role") != "vendor":
        raise _access_denied(
            "This account is not registered as a vendor."
        )

    if profile.get("is_active") is not True:
        raise _access_denied(
            "Vendor account is inactive."
        )

    # --------------------------------------------------------
    # 3. LOAD ACTIVE VENDOR MEMBERSHIP
    #
    # Inactive invited employees are excluded.
    #
    # Do not silently select a membership if more
    # than one active membership is found.
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

        memberships = (
            membership_response.data or []
        )

    except Exception as exc:
        logger.exception(
            "Vendor login membership lookup failed."
        )

        raise _database_unavailable(
            "Unable to verify vendor membership."
        ) from exc

    if not memberships:
        raise _access_denied(
            "No active vendor membership was found."
        )

    if len(memberships) != 1:
        raise _access_denied(
            "Multiple active vendor memberships "
            "require account review."
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
        raise _access_denied(
            "Invalid vendor membership role."
        )

    if permission_mode not in {
        "legacy",
        "custom",
    }:
        raise _access_denied(
            "Invalid vendor permission mode."
        )

    if not vendor_id:
        raise _access_denied(
            "Vendor membership is incomplete."
        )

    # --------------------------------------------------------
    # 4. LOAD VENDOR BUSINESS
    #
    # Owner response compatibility is preserved.
    #
    # Employee responses are restricted.
    # --------------------------------------------------------

    try:
        vendor_response = (
            supabase_admin
            .table("vendors")
            .select(
                "id, business_name, slug, email, "
                "phone, logo_url, status, "
                "commission_rate, is_active"
            )
            .eq("id", vendor_id)
            .limit(1)
            .execute()
        )

        vendors = (
            vendor_response.data or []
        )

    except Exception as exc:
        logger.exception(
            "Vendor login business lookup failed."
        )

        raise _database_unavailable(
            "Unable to verify vendor business."
        ) from exc

    if not vendors:
        raise _access_denied(
            "Vendor business was not found."
        )

    vendor = vendors[0]

    if vendor.get("is_active") is not True:
        raise _access_denied(
            "Vendor business is inactive."
        )

    # --------------------------------------------------------
    # 5. PREPARE ROLE-SPECIFIC RESPONSE
    #
    # Owner keeps existing vendor fields.
    #
    # Staff gets only the fields needed for
    # normal Vendor Web identity/navigation.
    #
    # Never expose commission_rate to staff.
    # --------------------------------------------------------

    is_owner = (
        member_role == "owner"
    )

    if is_owner:
        vendor_payload = vendor

    else:
        vendor_payload = {
            "id": vendor.get("id"),
            "business_name": vendor.get(
                "business_name"
            ),
            "slug": vendor.get("slug"),
            "logo_url": vendor.get("logo_url"),
            "status": vendor.get("status"),
            "is_active": vendor.get(
                "is_active"
            ),
        }

    # --------------------------------------------------------
    # 6. RETURN AUTHENTICATED LOGIN SESSION
    #
    # Effective permissions should be fetched
    # using GET /api/v1/vendor/auth/me.
    #
    # Do not compute permissions using untrusted
    # frontend-provided values.
    # --------------------------------------------------------

    return {
        "access_token": (
            session.access_token
        ),

        "refresh_token": (
            session.refresh_token
        ),

        "token_type": "bearer",

        "expires_in": (
            session.expires_in
        ),

        "user": {
            "id": user_id,
            "email": user.email,
            "full_name": profile.get(
                "full_name"
            ),
            "phone": profile.get(
                "phone"
            ),
            "role": profile.get(
                "role"
            ),
        },

        "membership": {
            "member_role": member_role,
        },

        "vendor": vendor_payload,
    }


"""
AUMVEDA Vendor Backend
Vendor Authentication API

Features:
- Vendor Owner registration
- Vendor Owner / Staff login
- Authenticated account information
- Secure staff invitation activation

Security:
- Existing Vendor Owner behavior preserved
- Supabase Auth validates employee credentials
- Staff activation uses authenticated user ID
- No client-provided vendor ID or role ID
- Database RPC enforces pending membership
- Owner-only capabilities remain protected

POST /auth/accept-invite:
Called only after the employee has followed the
Supabase invitation link and set their password.

The activation service performs a fresh password
authentication and then invokes the privileged
PostgreSQL activation function.
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    SecretStr,
)

from supabase import create_client

from app.core.config import settings
from app.core.supabase import supabase_admin

from app.dependencies.vendor import (
    get_current_vendor,
)

from app.dependencies.vendor_permissions import (
    resolve_vendor_permissions,
)

from app.schemas.vendor.auth import (
    VendorLoginRequest,
    VendorRegisterRequest,
)

from app.services.vendor.auth_service import (
    login_vendor,
    register_vendor,
)


logger = logging.getLogger(
    "aumveda.vendor.auth_api"
)


router = APIRouter(
    prefix="/auth",
    tags=["Vendor Authentication"],
)


# ============================================================
# STAFF INVITATION ACCEPTANCE REQUEST
#
# A password is required to prove that the employee
# has established working login credentials.
#
# Do not accept vendor_id, user_id or role_ids here.
# ============================================================

class VendorStaffAcceptInvitationRequest(
    BaseModel
):
    email: EmailStr

    password: SecretStr = Field(
        min_length=1,
    )


# ============================================================
# VENDOR REGISTRATION
#
# Existing Vendor Owner registration is preserved.
# Employees must never use this endpoint.
# ============================================================

@router.post("/register")
def vendor_register(
    payload: VendorRegisterRequest,
):
    return register_vendor(
        payload.model_dump()
    )


# ============================================================
# VENDOR / STAFF LOGIN
#
# Existing login mechanism is preserved.
# Staff must have an active membership to log in.
# ============================================================

@router.post("/login")
def vendor_login(
    payload: VendorLoginRequest,
):
    return login_vendor(
        email=payload.email,
        password=payload.password,
    )


# ============================================================
# STAFF INVITATION ACCEPTANCE
#
# POST /api/v1/vendor/auth/accept-invite
#
# Steps:
# 1. Verify credentials with Supabase Auth.
# 2. Get the authenticated Supabase user ID.
# 3. Call the protected activation RPC.
# 4. Return a confirmation without session tokens.
#
# PostgreSQL independently verifies:
# - Auth invitation history
# - Confirmed email
# - Password existence
# - Sign-in history
# - Pending invitation state
# - Inactive custom-mode staff membership
# - Active profile and approved vendor
# - At least one active custom role
#
# Neither vendor ID nor employee ID is trusted
# from the request body.
# ============================================================

@router.post(
    "/accept-invite",
    status_code=status.HTTP_200_OK,
)
def vendor_accept_staff_invitation(
    payload: VendorStaffAcceptInvitationRequest,
):
    # --------------------------------------------------------
    # 1. NORMALIZE EMPLOYEE EMAIL
    # --------------------------------------------------------

    employee_email = (
        str(payload.email)
        .strip()
        .lower()
    )

    employee_password = (
        payload.password.get_secret_value()
    )

    # --------------------------------------------------------
    # 2. FRESH SUPABASE PASSWORD AUTHENTICATION
    #
    # A separate client is used for this request.
    # Never authenticate with the service-role key.
    # --------------------------------------------------------

    try:
        auth_client = create_client(
            settings.supabase_url,
            settings.auth_client_key,
        )

        auth_response = (
            auth_client.auth.sign_in_with_password({
                "email": employee_email,
                "password": employee_password,
            })
        )

    except Exception:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail=(
                "Unable to verify employee credentials."
            ),
        )

    # --------------------------------------------------------
    # 3. REQUIRE AUTHENTICATED USER AND SESSION
    # --------------------------------------------------------

    invited_user = getattr(
        auth_response,
        "user",
        None,
    )

    invited_session = getattr(
        auth_response,
        "session",
        None,
    )

    if not invited_user or not invited_session:
        raise HTTPException(
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            detail=(
                "Unable to verify employee credentials."
            ),
        )

    # --------------------------------------------------------
    # 4. VERIFY AUTHENTICATED EMAIL
    #
    # This prevents accidental activation using
    # an unrelated authenticated account.
    # --------------------------------------------------------

    authenticated_email = (
        str(
            getattr(
                invited_user,
                "email",
                "",
            ) or ""
        )
        .strip()
        .lower()
    )

    if (
        not authenticated_email
        or authenticated_email != employee_email
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "Employee invitation identity mismatch."
            ),
        )

    # --------------------------------------------------------
    # 5. DERIVE USER ID FROM SUPABASE AUTH
    #
    # Never use a client-supplied user ID.
    # --------------------------------------------------------

    invited_user_id = str(
        invited_user.id
    )

    # --------------------------------------------------------
    # 6. ACTIVATE PENDING MEMBERSHIP
    #
    # Only the backend service-role client calls
    # activate_vendor_staff_invitation.
    #
    # The function is expected to reject:
    # - Existing Vendor Owners
    # - Non-invited users
    # - Already accepted employees
    # - Revoked invitations
    # - Owner-blocked accounts
    # - Accounts with no active custom roles
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .rpc(
                "activate_vendor_staff_invitation",
                {
                    "p_user_id": invited_user_id,
                },
            )
            .execute()
        )

    except Exception as exc:
        error_code = str(
            getattr(
                exc,
                "code",
                "",
            ) or ""
        )

        # Expected database validation failures.
        # Do not expose internal SQL details.

        if error_code in {
            "22023",
            "P0002",
        }:
            raise HTTPException(
                status_code=(
                    status.HTTP_403_FORBIDDEN
                ),
                detail=(
                    "This invitation cannot be activated. "
                    "It may already be accepted, revoked, "
                    "or not eligible for activation."
                ),
            ) from exc

        logger.exception(
            "Staff invitation activation RPC failed."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Unable to complete staff account "
                "activation. Please try again or "
                "contact the Vendor Owner."
            ),
        ) from exc

    # --------------------------------------------------------
    # 7. SUCCESS
    #
    # Do not return:
    # - Access tokens
    # - Refresh tokens
    # - Passwords
    # - Invitation nonces
    # - Service credentials
    #
    # Employee should log in through the existing
    # Vendor Web login endpoint after activation.
    # --------------------------------------------------------

    return {
        "status": "success",
        "message": (
            "Your employee account has been activated "
            "successfully. You can now log in to "
            "AUMVEDA Vendor Web."
        ),
        "next_step": "login",
    }


# ============================================================
# CURRENT AUTHENTICATED ACCOUNT
#
# GET /api/v1/vendor/auth/me
#
# Preserve existing response compatibility.
# ============================================================

@router.get("/me")
def vendor_me(
    vendor_context=Depends(
        get_current_vendor
    ),
):
    user = vendor_context["user"]

    profile = vendor_context["profile"]

    membership = vendor_context["membership"]

    vendor = vendor_context["vendor"]

    member_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    vendor_status = str(
        vendor.get("status") or ""
    ).strip().lower()

    is_approved = (
        vendor_status == "approved"
    )

    # --------------------------------------------------------
    # PERMISSIONS
    #
    # Existing owner and staff behavior preserved.
    # --------------------------------------------------------

    if is_approved:
        permissions = sorted(
            resolve_vendor_permissions(
                vendor_context
            )
        )
    else:
        permissions = []

    is_owner = (
        member_role == "owner"
    )

    # --------------------------------------------------------
    # OWNER-SPECIFIC AND STAFF-SPECIFIC DATA
    # --------------------------------------------------------

    if is_owner:
        vendor_payload = vendor

    else:
        vendor_payload = {
            "id": vendor.get("id"),
            "business_name": vendor.get(
                "business_name"
            ),
            "status": vendor.get("status"),
            "is_active": vendor.get(
                "is_active"
            ),
        }

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {
        "user": {
            "id": str(user.id),
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

        "authorization": {
            "is_owner": is_owner,
            "vendor_approved": is_approved,
            "permissions": permissions,
        },
    }

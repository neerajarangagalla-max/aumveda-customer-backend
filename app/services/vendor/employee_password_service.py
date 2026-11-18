
"""
AUMVEDA Vendor Backend
Owner-Managed Employee Password Reset Service

Workflow:
1. Validate Vendor and employee identifiers.
2. Reject Owner self-management.
3. Verify employee membership in this vendor.
4. Reject Vendor Owner target accounts.
5. Verify active vendor profile.
6. Verify employee Supabase Auth identity.
7. Update password using Supabase Auth Admin API.
8. Return a safe confirmation.

Security:
- Only callable through get_vendor_owner.
- Vendor ID comes from authenticated context.
- Password is never logged.
- Password is never returned.
- Password is never stored in application tables.
- Existing role assignments are preserved.
- No Auth identity is created or deleted.
- No automatic password-update retries.

Session note:
Changing the password does not provide a guarantee
that every previously issued access token is
immediately unusable. Token/session revocation
is a separate security consideration.
"""

import logging
from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.employee_password"
)


# ============================================================
# ERROR HELPERS
# ============================================================

def _error(
    status_code: int,
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=message,
    )


def _normalize_uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Invalid employee or vendor identifier.",
        ) from None


# ============================================================
# VERIFY EMPLOYEE MEMBERSHIP
# ============================================================

def _verify_employee_membership(
    *,
    vendor_id: str,
    employee_user_id: str,
) -> dict:

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .select(
                "vendor_id, user_id, member_role, "
                "is_active, permission_mode"
            )
            .eq("vendor_id", vendor_id)
            .eq("user_id", employee_user_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception:
        logger.exception(
            "Employee password reset: "
            "membership lookup failed."
        )

        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Unable to verify employee membership.",
        ) from None

    if not rows:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "This employee does not belong to your vendor team.",
        )

    membership = rows[0]

    member_role = str(
        membership.get("member_role") or ""
    ).strip().lower()

    if member_role == "owner":
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "Vendor Owner passwords cannot be "
            "changed through Team Management.",
        )

    if member_role not in {
        "manager",
        "staff",
        "inventory",
        "orders",
    }:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "This account is not an eligible vendor employee.",
        )

    return membership


# ============================================================
# VERIFY EMPLOYEE PROFILE
# ============================================================

def _verify_employee_profile(
    employee_user_id: str,
) -> None:

    try:
        response = (
            supabase_admin
            .table("profiles")
            .select("id, role, is_active")
            .eq("id", employee_user_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception:
        logger.exception(
            "Employee password reset: "
            "profile lookup failed."
        )

        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Unable to verify employee profile.",
        ) from None

    if not rows:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "Employee profile was not found.",
        )

    profile = rows[0]

    if profile.get("role") != "vendor":
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "The selected account is not a vendor employee profile.",
        )

    # Inactive accounts may legitimately require
    # password recovery, but resetting their password
    # must never change their active/inactive state.


# ============================================================
# VERIFY SUPABASE AUTH IDENTITY
# ============================================================

def _verify_auth_identity(
    employee_user_id: str,
) -> None:

    try:
        response = (
            supabase_admin
            .auth
            .admin
            .get_user_by_id(employee_user_id)
        )

        auth_user = getattr(
            response,
            "user",
            None,
        )

    except Exception:
        logger.exception(
            "Employee password reset: "
            "Auth identity verification failed."
        )

        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Unable to verify employee Auth identity.",
        ) from None

    if auth_user is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "Employee Auth account was not found.",
        )

    if str(auth_user.id) != employee_user_id:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Employee Auth identity verification failed.",
        )


# ============================================================
# RESET EMPLOYEE PASSWORD
# ============================================================

def reset_vendor_employee_password(
    *,
    vendor_id: str,
    employee_user_id: str,
    current_user_id: str,
    new_password: str,
) -> dict:

    normalized_vendor_id = _normalize_uuid(
        vendor_id
    )

    normalized_employee_id = _normalize_uuid(
        employee_user_id
    )

    normalized_owner_id = _normalize_uuid(
        current_user_id
    )

    # --------------------------------------------------------
    # 1. PROTECT ACTING VENDOR OWNER
    # --------------------------------------------------------

    if normalized_employee_id == normalized_owner_id:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "You cannot reset your own Owner password "
            "through employee management.",
        )

    # --------------------------------------------------------
    # 2. VALIDATE PASSWORD
    #
    # No application-specific password length limit.
    # Supabase Auth applies its configured requirements.
    #
    # Do not trim or log password values.
    # --------------------------------------------------------

    if not isinstance(new_password, str):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "A valid new password is required.",
        )

    if len(new_password) == 0:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "New password cannot be empty.",
        )

    # --------------------------------------------------------
    # 3. VERIFY TARGET EMPLOYEE
    # --------------------------------------------------------

    _verify_employee_membership(
        vendor_id=normalized_vendor_id,
        employee_user_id=normalized_employee_id,
    )

    # --------------------------------------------------------
    # 4. VERIFY EMPLOYEE PROFILE
    # --------------------------------------------------------

    _verify_employee_profile(
        normalized_employee_id
    )

    # --------------------------------------------------------
    # 5. VERIFY AUTH IDENTITY
    # --------------------------------------------------------

    _verify_auth_identity(
        normalized_employee_id
    )

    # --------------------------------------------------------
    # 6. RECHECK MEMBERSHIP BEFORE MUTATION
    #
    # Do not proceed if membership was removed
    # between initial checks and Auth verification.
    # --------------------------------------------------------

    _verify_employee_membership(
        vendor_id=normalized_vendor_id,
        employee_user_id=normalized_employee_id,
    )

    # --------------------------------------------------------
    # 7. UPDATE PASSWORD IN SUPABASE AUTH
    #
    # Auth Admin API:
    # update_user_by_id(user_id, {"password": ...})
    #
    # No application database password writes.
    # --------------------------------------------------------

    try:
        response = (
            supabase_admin
            .auth
            .admin
            .update_user_by_id(
                normalized_employee_id,
                {
                    "password": new_password,
                },
            )
        )

    except Exception as exc:
        # Do not log the full exception:
        # Auth errors may contain sensitive data.

        logger.error(
            "Employee password reset failed. "
            "employee_id=%s vendor_id=%s "
            "exception_type=%s auth_error_code=%s",
            normalized_employee_id,
            normalized_vendor_id,
            type(exc).__name__,
            getattr(exc, "code", None),
        )

        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Employee password update could not be "
            "confirmed. Review the account before retrying.",
        ) from None

    # --------------------------------------------------------
    # 8. VERIFY AUTH RESPONSE
    # --------------------------------------------------------

    updated_user = getattr(
        response,
        "user",
        None,
    )

    if updated_user is None:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Supabase Auth did not confirm the password "
            "update. Check the account before retrying.",
        )

    if str(updated_user.id) != normalized_employee_id:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Employee Auth identity mismatch after "
            "password update.",
        )

    # --------------------------------------------------------
    # 9. SUCCESS
    #
    # Password and credentials are never returned.
    # --------------------------------------------------------

    logger.info(
        "Employee password updated. "
        "employee_id=%s vendor_id=%s",
        normalized_employee_id,
        normalized_vendor_id,
    )

    return {
        "status": "success",

        "message": (
            "Employee password updated successfully. "
            "The employee can use the new password "
            "for their next login."
        ),

        "user_id": normalized_employee_id,

        "password_updated": True,
    }


"""
AUMVEDA Vendor Backend
Employee Removal Service

Workflow:
- Vendor Owner selects an employee.
- Backend verifies vendor-specific membership.
- Owner membership cannot be removed.
- Employee membership is deleted.
- Assigned custom roles are removed through
  the existing database ON DELETE CASCADE.
- Supabase Auth identity is preserved.

Security:
- Only callable from Owner-protected API routes.
- Vendor ID and acting user come from auth context.
- No Supabase Auth user deletion.
- No profile deletion.
- No cross-vendor membership deletion.
"""

import logging
from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


logger = logging.getLogger(
    "aumveda.vendor.employee_removal"
)


def _normalize_uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail="Invalid employee identifier.",
        ) from None


def remove_vendor_employee(
    *,
    vendor_id: str,
    user_id: str,
    current_user_id: str,
) -> dict:

    vendor_id = _normalize_uuid(vendor_id)
    user_id = _normalize_uuid(user_id)
    current_user_id = _normalize_uuid(
        current_user_id
    )

    # Never allow the acting Owner to remove
    # their own membership.

    if user_id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "You cannot remove your own "
                "Vendor Owner account."
            ),
        )

    # Find only the membership belonging
    # to the authenticated vendor.

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .select(
                "user_id, vendor_id, member_role"
            )
            .eq("vendor_id", vendor_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
    except Exception:
        logger.exception(
            "Unable to verify employee membership."
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to verify employee membership."
            ),
        ) from None

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                "Employee is not part of this "
                "vendor team."
            ),
        )

    membership = rows[0]

    # Owner memberships are always protected.

    if (
        str(
            membership.get("member_role") or ""
        ).strip().lower() == "owner"
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Vendor Owner accounts cannot "
                "be deleted through Team Management."
            ),
        )

    # Delete only a non-owner membership.
    #
    # Database FK:
    # vendor_member_custom_roles_member_fk
    # ON DELETE CASCADE
    #
    # This removes assigned custom roles when
    # the vendor membership is deleted.
    #
    # Any other database FK restrictions may
    # reject deletion; the service must fail
    # rather than remove unrelated records.

    try:
        response = (
            supabase_admin
            .table("vendor_members")
            .delete()
            .eq("vendor_id", vendor_id)
            .eq("user_id", user_id)
            .neq("member_role", "owner")
            .select("user_id")
            .execute()
        )

        deleted_rows = response.data or []

    except Exception:
        logger.exception(
            "Employee membership removal failed."
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Employee removal could not be "
                "completed. No successful deletion "
                "was confirmed."
            ),
        ) from None

    if len(deleted_rows) != 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Employee membership could not "
                "be removed. Refresh the team "
                "and check the employee's status."
            ),
        )

    logger.info(
        "Vendor employee membership removed. "
        "vendor_id=%s employee_id=%s",
        vendor_id,
        user_id,
    )

    return {
        "status": "success",
        "message": (
            "Employee removed from the vendor "
            "team successfully."
        ),
        "user_id": user_id,
        "vendor_id": vendor_id,
        "auth_account_deleted": False,
    }

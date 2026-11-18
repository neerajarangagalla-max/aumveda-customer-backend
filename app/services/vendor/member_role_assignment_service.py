
from uuid import UUID

from fastapi import HTTPException, status

from app.core.supabase import supabase_admin


# ============================================================
# ASSIGN CUSTOM ROLES TO VENDOR MEMBER
# ============================================================

def assign_vendor_member_custom_roles(
    vendor_id: str,
    user_id: str,
    assigned_by: str,
    role_ids: list[UUID],
):
    # --------------------------------------------------------
    # NORMALIZE ROLE IDS
    # --------------------------------------------------------

    normalized_role_ids = sorted({
        str(role_id)
        for role_id in role_ids
    })

    if not normalized_role_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Select at least one custom role.",
        )

    # --------------------------------------------------------
    # CALL ATOMIC DATABASE FUNCTION
    # --------------------------------------------------------

    try:
        (
            supabase_admin
            .rpc(
                "assign_vendor_member_roles_atomic",
                {
                    "p_vendor_id": vendor_id,
                    "p_user_id": user_id,
                    "p_role_ids": normalized_role_ids,
                    "p_assigned_by": assigned_by,
                },
            )
            .execute()
        )

    except Exception as exc:
        error_code = getattr(
            exc,
            "code",
            None,
        )

        if error_code == "P0002":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor team member not found.",
            )

        if error_code == "22023":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Invalid custom role assignment. "
                    "Verify that the roles are active "
                    "and belong to your business."
                ),
            )

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to assign custom roles.",
        )

    # --------------------------------------------------------
    # RETURN SAVED ASSIGNMENTS
    # --------------------------------------------------------

    try:
        membership_response = (
            supabase_admin
            .table("vendor_members")
            .select(
                "vendor_id, user_id, member_role, "
                "is_active, permission_mode"
            )
            .eq("vendor_id", vendor_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )

        memberships = membership_response.data or []

        assignments_response = (
            supabase_admin
            .table("vendor_member_custom_roles")
            .select("role_id, assigned_at")
            .eq("vendor_id", vendor_id)
            .eq("user_id", user_id)
            .execute()
        )

        assignments = assignments_response.data or []

        if not memberships:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vendor team member not found.",
            )

        return {
            "status": "success",
            "message": "Custom roles assigned successfully.",
            "membership": memberships[0],
            "assigned_roles": assignments,
        }

    except HTTPException:
        raise

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Roles were updated, but the saved "
                "assignments could not be retrieved."
            ),
        )

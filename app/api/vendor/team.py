
"""
AUMVEDA Vendor Backend
Team Management API

Endpoints:
- GET    /team
- GET    /team/{user_id}
- PATCH  /team/{user_id}/role
- PATCH  /team/{user_id}/status
- PUT    /team/{user_id}/custom-roles
- DELETE /team/{user_id}
- PATCH  /team/{user_id}/password

Security:
- Vendor Owner authentication required.
- UUID-only member routes.
- Vendor-specific membership isolation.
- Vendor Owner protected from staff mutations.
- Employee passwords updated through Supabase Auth.
- No passwords returned in API responses.
"""

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.schemas.vendor.team import (
    VendorMemberRoleUpdateRequest,
    VendorMemberStatusUpdateRequest,
    VendorMemberCustomRolesRequest,
)

from app.schemas.vendor.employee_password import (
    VendorEmployeePasswordResetRequest,
    VendorEmployeePasswordResetResponse,
)

from app.services.vendor.team_service import (
    get_vendor_member,
    list_vendor_members,
    update_vendor_member_role,
    update_vendor_member_status,
)

from app.services.vendor.member_role_assignment_service import (
    assign_vendor_member_custom_roles,
)

from app.services.vendor.employee_removal_service import (
    remove_vendor_employee,
)

from app.services.vendor.employee_password_service import (
    reset_vendor_employee_password,
)


router = APIRouter(
    prefix="/team",
    tags=["Vendor Team"],
)


# ============================================================
# LIST TEAM MEMBERS
# ============================================================

@router.get("")
def vendor_team(
    vendor_context=Depends(get_vendor_owner),
):
    return list_vendor_members(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
    )


# ============================================================
# GET TEAM MEMBER
# ============================================================

@router.get("/{user_id:uuid}")
def vendor_team_member(
    user_id: UUID,
    vendor_context=Depends(get_vendor_owner),
):
    return get_vendor_member(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        user_id=str(user_id),
    )


# ============================================================
# UPDATE MEMBER ROLE
# ============================================================

@router.patch("/{user_id:uuid}/role")
def vendor_update_team_role(
    user_id: UUID,
    payload: VendorMemberRoleUpdateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    current_user = vendor_context["user"]

    return update_vendor_member_role(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        user_id=str(user_id),
        member_role=payload.member_role,
        current_user_id=str(current_user.id),
    )


# ============================================================
# ACTIVATE / DEACTIVATE EMPLOYEE
# ============================================================

@router.patch("/{user_id:uuid}/status")
def vendor_update_team_status(
    user_id: UUID,
    payload: VendorMemberStatusUpdateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    current_user = vendor_context["user"]

    return update_vendor_member_status(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        user_id=str(user_id),
        is_active=payload.is_active,
        current_user_id=str(current_user.id),
    )


# ============================================================
# ASSIGN CUSTOM ROLES
# ============================================================

@router.put("/{user_id:uuid}/custom-roles")
def vendor_assign_member_custom_roles(
    user_id: UUID,
    payload: VendorMemberCustomRolesRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return assign_vendor_member_custom_roles(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        user_id=str(user_id),
        assigned_by=str(
            vendor_context["user_id"]
        ),
        role_ids=payload.role_ids,
    )


# ============================================================
# DELETE EMPLOYEE VENDOR MEMBERSHIP
#
# Auth identity and profile are preserved.
# ============================================================

@router.delete("/{user_id:uuid}")
def vendor_delete_employee(
    user_id: UUID,
    vendor_context=Depends(get_vendor_owner),
):
    return remove_vendor_employee(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        user_id=str(user_id),
        current_user_id=str(
            vendor_context["user_id"]
        ),
    )


# ============================================================
# RESET EMPLOYEE PASSWORD
#
# Only the Vendor Owner can call this endpoint.
# Supabase Auth stores the password hash.
#
# No employee account creation, deletion,
# membership or custom-role changes occur.
# ============================================================

@router.patch(
    "/{user_id:uuid}/password",
    response_model=VendorEmployeePasswordResetResponse,
)
def vendor_reset_employee_password(
    user_id: UUID,
    payload: VendorEmployeePasswordResetRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return reset_vendor_employee_password(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),
        employee_user_id=str(user_id),
        current_user_id=str(
            vendor_context["user_id"]
        ),
        new_password=(
            payload.new_password.get_secret_value()
        ),
    )


"""
AUMVEDA Vendor Backend
Owner-Created Employee Account API

Endpoint:
POST /api/v1/vendor/team/employees

Features:
- Vendor Owner creates an employee account
- Owner chooses initial employee password
- One or more custom roles can be assigned
- Supabase Auth manages the employee credentials
- PostgreSQL creates the vendor membership
- Existing email-invitation flow remains separate

Security:
- Approved Vendor Owner only
- Vendor ID derived from authenticated context
- Creator ID derived from authenticated context
- No client-selected member_role or vendor_id
- Custom roles verified by the service and database
- Password never returned in the API response
- Owner-only privileges cannot be assigned
"""

from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.schemas.vendor.staff_creation import (
    VendorStaffCreateRequest,
    VendorStaffCreateResponse,
)

from app.services.vendor.staff_creation_service import (
    create_vendor_staff,
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/team",
    tags=["Vendor Team Management"],
)


# ============================================================
# CREATE EMPLOYEE
#
# POST /api/v1/vendor/team/employees
#
# Requires:
# - Valid Supabase Auth session
# - Active Vendor Owner membership
# - Approved and active vendor business
#
# The request must contain:
# - full_name
# - email
# - password
# - role_ids
#
# Never accept vendor_id, user_id, created_by
# or member_role from the frontend.
# ============================================================

@router.post(
    "/employees",
    response_model=VendorStaffCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def vendor_create_employee(
    payload: VendorStaffCreateRequest,
    vendor_context=Depends(
        get_vendor_owner
    ),
):
    """
    Create a new employee for the authenticated
    Vendor Owner's business.

    The employee is provisioned through:
    - Supabase Auth Admin API
    - Verified PostgreSQL atomic provisioning RPC

    Employees can log in using the password
    initially provided by the Vendor Owner.
    """

    return create_vendor_staff(
        vendor_id=str(
            vendor_context["vendor_id"]
        ),

        created_by=str(
            vendor_context["user_id"]
        ),

        full_name=payload.full_name,

        email=str(payload.email),

        password=(
            payload.password.get_secret_value()
        ),

        role_ids=payload.role_ids,
    )

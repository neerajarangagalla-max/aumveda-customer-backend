
"""
AUMVEDA Vendor Backend
Business Profile API

Access:
- GET /profile: Authenticated vendor context
- PATCH /profile: Approved Vendor Owner only

Security:
- Vendor ID is derived from authentication.
- Staff cannot modify business information.
- Platform-managed fields cannot be updated.
- Branding approval uses separate APIs.
"""

from fastapi import APIRouter, Depends

from app.dependencies.vendor import (
    get_current_vendor,
    get_vendor_owner,
)

from app.schemas.vendor.profile import (
    VendorProfileUpdateRequest,
)

from app.services.vendor.profile_service import (
    get_vendor_profile,
    update_vendor_profile,
)


router = APIRouter(
    prefix="/profile",
    tags=["Vendor Profile"],
)


# ============================================================
# GET BUSINESS PROFILE
#
# Authenticated vendor account.
# ============================================================

@router.get("")
def read_vendor_profile(
    vendor_context=Depends(get_current_vendor),
):
    return get_vendor_profile(
        vendor_id=str(vendor_context["vendor_id"]),
    )


# ============================================================
# UPDATE BUSINESS PROFILE
#
# Vendor Owner only.
#
# Branding, approval status and financial settings
# are not editable through this endpoint.
# ============================================================

@router.patch("")
def edit_vendor_profile(
    payload: VendorProfileUpdateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return update_vendor_profile(
        vendor_id=str(vendor_context["vendor_id"]),
        payload=payload.model_dump(
            exclude_unset=True,
        ),
    )

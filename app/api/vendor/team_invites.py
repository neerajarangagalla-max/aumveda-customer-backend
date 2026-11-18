
from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.schemas.vendor.staff_invitation import (
    VendorStaffInvitationRequest,
)

from app.services.vendor.staff_invitation_service import (
    invite_vendor_staff,
)


router = APIRouter(
    prefix="/team",
    tags=["Vendor Team Invitations"],
)


# ============================================================
# INVITE STAFF MEMBER
#
# OWNER ONLY
#
# Vendor ID and inviter ID are always obtained
# from the authenticated Owner context.
# ============================================================

@router.post(
    "/invite",
    status_code=status.HTTP_201_CREATED,
)
def vendor_invite_staff(
    payload: VendorStaffInvitationRequest,
    vendor_context=Depends(get_vendor_owner),
):
    return invite_vendor_staff(
        vendor_id=vendor_context["vendor_id"],
        invited_by=vendor_context["user_id"],
        full_name=payload.full_name,
        email=str(payload.email),
        role_ids=payload.role_ids,
    )

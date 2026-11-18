
from fastapi import APIRouter, Depends

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.services.vendor.dashboard_service import (
    get_vendor_dashboard,
)


router = APIRouter(
    prefix="/dashboard",
    tags=["Vendor Dashboard"],
)


# ============================================================
# VENDOR DASHBOARD
#
# OWNER ONLY (TEMPORARY SECURITY RESTRICTION)
#
# The dashboard service has not yet been audited
# for financial fields.
#
# Once we create a sanitized operational dashboard,
# permitted staff members can be allowed to access
# that separate response.
# ============================================================

@router.get("")
def vendor_dashboard(
    vendor_context=Depends(
        get_vendor_owner
    ),
):
    return get_vendor_dashboard(
        vendor_context["vendor_id"]
    )

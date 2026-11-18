
"""
AUMVEDA Vendor Backend
Vendor Earnings API

Features:
- Earnings summary
- Earnings ledger history
- Permission-based access
- Vendor-level data isolation
- Accounts team support

Access Policy:
1. Vendor Owner:
   Full access to Earnings.

2. Custom Accounts Role:
   Access only when explicitly assigned
   the earnings.view permission.

3. Legacy Manager:
   No automatic Earnings access.

4. Other Vendor Staff:
   No Earnings access unless granted
   earnings.view through custom roles.

5. Payout Management:
   Remains separately protected.

Security:
- Authenticated vendor context is required.
- Vendor membership must be active.
- Vendor must be approved.
- Earnings permission is checked by FastAPI.
- Vendor ID comes from authenticated context.
- Client-provided vendor IDs are never trusted.
"""

from fastapi import (
    APIRouter,
    Depends,
)

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.services.vendor.earnings_service import (
    get_vendor_earnings_summary,
    list_vendor_ledger_entries,
)


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/earnings",
    tags=["Vendor Earnings"],
)


# ============================================================
# PERMISSION DEPENDENCY
#
# Allows:
# - Vendor Owner
# - Custom-role staff with earnings.view
#
# Denies:
# - Staff without earnings.view
# - Inactive memberships
# - Unauthorized vendors
#
# The permission resolver enforces RBAC.
# ============================================================

require_earnings_view = require_vendor_permission(
    "earnings.view"
)


# ============================================================
# EARNINGS SUMMARY
#
# GET /api/v1/vendor/earnings/summary
#
# Required permission:
# earnings.view
# ============================================================

@router.get("/summary")
def vendor_earnings_summary(
    vendor_context=Depends(
        require_earnings_view
    ),
):
    """
    Return earnings summary for the
    authenticated vendor.

    The vendor_id is resolved from the
    authenticated membership context.

    Accounts staff cannot request earnings
    belonging to another vendor.
    """

    vendor_id = str(
        vendor_context["vendor_id"]
    )

    return get_vendor_earnings_summary(
        vendor_id
    )


# ============================================================
# EARNINGS HISTORY
#
# GET /api/v1/vendor/earnings
#
# Required permission:
# earnings.view
# ============================================================

@router.get("")
def vendor_earnings_history(
    vendor_context=Depends(
        require_earnings_view
    ),
):
    """
    Return ledger entries for the
    authenticated vendor.

    Only authorized users with earnings.view
    can access this endpoint.

    Payout actions remain separate from
    this read-only Earnings API.
    """

    vendor_id = str(
        vendor_context["vendor_id"]
    )

    return list_vendor_ledger_entries(
        vendor_id
    )

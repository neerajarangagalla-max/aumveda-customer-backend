
from fastapi import APIRouter, Depends

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.services.vendor.payout_service import (
    get_vendor_payout,
    get_vendor_payout_summary,
    list_vendor_payouts,
)


router = APIRouter(
    prefix="/payouts",
    tags=["Vendor Payouts"],
)


# ============================================================
# PAYOUT SUMMARY
# OWNER ONLY
# ============================================================

@router.get("/summary")
def vendor_payout_summary(
    vendor_context=Depends(
        get_vendor_owner
    ),
):
    return get_vendor_payout_summary(
        vendor_context["vendor_id"]
    )


# ============================================================
# PAYOUT LIST
# OWNER ONLY
# ============================================================

@router.get("")
def vendor_payouts(
    vendor_context=Depends(
        get_vendor_owner
    ),
):
    return list_vendor_payouts(
        vendor_context["vendor_id"]
    )


# ============================================================
# PAYOUT DETAIL
# OWNER ONLY
# ============================================================

@router.get("/{payout_id}")
def vendor_payout_detail(
    payout_id: str,
    vendor_context=Depends(
        get_vendor_owner
    ),
):
    return get_vendor_payout(
        vendor_id=vendor_context["vendor_id"],
        payout_id=payout_id,
    )

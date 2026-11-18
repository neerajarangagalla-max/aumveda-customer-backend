
"""
AUMVEDA Vendor Backend
Business Branding API

Policy:
- Logo changes are immediate.
- Banner changes are immediate.
- No Admin approval is required.
- Only the Vendor Owner can upload images.
- Approved vendor accounts may view branding.
- Legacy branding history remains read-only.

Base path:
    /api/v1/vendor/branding
"""

from fastapi import APIRouter, Depends, File, UploadFile

from app.dependencies.vendor import (
    get_approved_vendor,
    get_vendor_owner,
)

from app.services.vendor.branding_service import (
    get_vendor_branding,
    list_vendor_branding_requests,
    upload_vendor_branding_image,
)


router = APIRouter(
    prefix="/branding",
    tags=["Vendor Branding"],
)


# ============================================================
# GET CURRENT BRANDING
# ============================================================

@router.get("")
def vendor_branding(
    vendor_context=Depends(get_approved_vendor),
):
    return get_vendor_branding(
        vendor_id=str(vendor_context["vendor_id"]),
    )


# ============================================================
# GET LEGACY BRANDING HISTORY
# Owner only.
# Historical records are preserved.
# ============================================================

@router.get("/requests")
def vendor_branding_requests(
    vendor_context=Depends(get_vendor_owner),
):
    return list_vendor_branding_requests(
        vendor_id=str(vendor_context["vendor_id"]),
    )


# ============================================================
# UPLOAD LOGO
# Owner only. Applies immediately.
# ============================================================

@router.post("/logo")
async def vendor_branding_logo(
    file: UploadFile = File(...),
    vendor_context=Depends(get_vendor_owner),
):
    return await upload_vendor_branding_image(
        vendor_id=str(vendor_context["vendor_id"]),
        request_type="logo",
        file=file,
    )


# ============================================================
# UPLOAD BANNER
# Owner only. Applies immediately.
# ============================================================

@router.post("/banner")
async def vendor_branding_banner(
    file: UploadFile = File(...),
    vendor_context=Depends(get_vendor_owner),
):
    return await upload_vendor_branding_image(
        vendor_id=str(vendor_context["vendor_id"]),
        request_type="banner",
        file=file,
    )

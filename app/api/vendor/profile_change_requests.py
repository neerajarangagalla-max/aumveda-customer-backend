
"""
AUMVEDA Vendor Backend
Business Profile Change Request API

STEP 19.9.6

Purpose:
- Submit business profile changes for Admin approval.
- View submitted requests.
- View individual change requests.

Security:
- All endpoints require approved Vendor Owner access.
- Vendor ID comes from authenticated vendor context.
- User ID comes from authenticated Supabase identity.
- Vendor IDs are never accepted from request payloads.
- Request status cannot be changed by vendors.
- Admin approval and rejection are handled separately.

Endpoints:
POST /profile/change-requests
GET  /profile/change-requests
GET  /profile/change-requests/{request_id}

Important:
- The Vendor Backend only submits and reads requests.
- It never approves or rejects requests.
- Approved vendor information remains unchanged
  until the Admin Backend applies an approved request.
"""

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Path,
    status,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.schemas.vendor.profile_change_requests import (
    VendorProfileChangeCreateRequest,
    VendorProfileChangeListResponse,
    VendorProfileChangeResponse,
    VendorProfileChangeSubmitResponse,
)

from app.services.vendor.profile_change_request_service import (
    create_vendor_profile_change_request,
    get_vendor_profile_change_request,
    list_vendor_profile_change_requests,
)


# ============================================================
# ROUTER CONFIGURATION
#
# This router must be included under the existing
# Vendor API prefix.
#
# If the Vendor main router uses:
# /api/v1/vendor
#
# The complete route becomes:
# /api/v1/vendor/profile/change-requests
# ============================================================

router = APIRouter(
    prefix="/profile/change-requests",
    tags=["Vendor Profile Change Requests"],
)


# ============================================================
# SUBMIT BUSINESS PROFILE CHANGE REQUEST
#
# POST /profile/change-requests
#
# Access:
# Approved Vendor Owner only.
#
# Example request:
#
# {
#     "section": "store_information",
#     "proposed_changes": {
#         "business_name": "Intelera Ayurveda",
#         "description": "Ayurvedic wellness products"
#     }
# }
#
# Important:
# - vendor_id comes from authentication.
# - submitted_by comes from authentication.
# - status is always pending.
# - No changes are applied to the vendors table.
# ============================================================

@router.post(
    "",
    response_model=VendorProfileChangeSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit business profile change request",
    description=(
        "Submit Store Information, Business Address, "
        "or Legal & Tax changes for Admin approval. "
        "Existing approved business information remains "
        "unchanged until an Admin approves the request."
    ),
)
def submit_vendor_profile_change_request(
    payload: VendorProfileChangeCreateRequest,
    vendor_context=Depends(get_vendor_owner),
):
    vendor_id = str(
        vendor_context["vendor_id"]
    )

    user_id = str(
        vendor_context["user_id"]
    )

    return create_vendor_profile_change_request(
        vendor_id=vendor_id,
        submitted_by=user_id,
        payload=payload,
    )


# ============================================================
# LIST BUSINESS PROFILE CHANGE REQUESTS
#
# GET /profile/change-requests
#
# Access:
# Approved Vendor Owner only.
#
# Shows only requests belonging to the
# authenticated vendor.
#
# Includes:
# - Pending requests
# - Approved requests
# - Rejected requests
#
# Results are ordered by newest first.
# ============================================================

@router.get(
    "",
    response_model=VendorProfileChangeListResponse,
    status_code=status.HTTP_200_OK,
    summary="List business profile change requests",
    description=(
        "Retrieve business profile change requests "
        "belonging to the authenticated vendor. "
        "Requests are ordered by creation date."
    ),
)
def read_vendor_profile_change_requests(
    vendor_context=Depends(get_vendor_owner),
):
    vendor_id = str(
        vendor_context["vendor_id"]
    )

    return list_vendor_profile_change_requests(
        vendor_id=vendor_id,
    )


# ============================================================
# GET INDIVIDUAL BUSINESS PROFILE CHANGE REQUEST
#
# GET /profile/change-requests/{request_id}
#
# Access:
# Approved Vendor Owner only.
#
# Both vendor ID and request ID are required
# to retrieve a request.
#
# This prevents a vendor from reading another
# vendor's change request by guessing its UUID.
# ============================================================

@router.get(
    "/{request_id}",
    response_model=VendorProfileChangeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get business profile change request",
    description=(
        "Retrieve a specific business profile change "
        "request belonging to the authenticated vendor."
    ),
)
def read_vendor_profile_change_request(
    request_id: UUID = Path(
        ...,
        description=(
            "Unique business profile change request ID."
        ),
    ),
    vendor_context=Depends(get_vendor_owner),
):
    vendor_id = str(
        vendor_context["vendor_id"]
    )

    return get_vendor_profile_change_request(
        vendor_id=vendor_id,
        request_id=str(request_id),
    )

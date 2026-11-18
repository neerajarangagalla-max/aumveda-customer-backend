
"""
AUMVEDA Vendor Backend
Business Profile Service

STEP 19.9.9

Updated Business Profile Policy:

Admin approval required:
- Store Information
- Contact Information
- Business Address
- Legal & Tax Details

Immediate updates:
- Logo
- Banner

Security:
- Vendor ID comes from authentication.
- Staff cannot modify business information.
- No direct profile-field updates are permitted.
- All business information changes must pass
  through the Admin approval workflow.
- Logo and banner updates use separate APIs.

Current implementation:
- GET profile remains available.
- PATCH profile is temporarily disabled for all
  direct changes until the approval-request
  workflow is fully integrated.
"""

import logging

from fastapi import (
    HTTPException,
    status,
)

from app.core.supabase import (
    supabase_admin,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "aumveda.vendor.profile"
)


# ============================================================
# FIELDS REQUIRING ADMIN APPROVAL
# ============================================================

APPROVAL_REQUIRED_FIELDS = frozenset({
    # Store Information
    "business_name",
    "description",

    # Contact Information
    "email",
    "phone",

    # Business Address
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",

    # Legal & Tax
    "legal_name",
    "tax_id",
})


# ============================================================
# BRANDING FIELDS
#
# These are updated only through the separate
# Branding API and do not require Admin approval.
# ============================================================

BRANDING_FIELDS = frozenset({
    "logo_url",
    "banner_url",
})


# ============================================================
# ERROR HELPERS
# ============================================================

def _profile_not_found() -> HTTPException:

    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Vendor profile was not found.",
    )


def _database_error() -> HTTPException:

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "Unable to process the business "
            "profile at this time."
        ),
    )


# ============================================================
# GET VENDOR BUSINESS PROFILE
#
# GET /api/v1/vendor/profile
#
# Existing functionality is preserved.
# ============================================================

def get_vendor_profile(
    vendor_id: str,
) -> dict:

    try:
        response = (
            supabase_admin
            .table("vendors")
            .select("*")
            .eq("id", str(vendor_id))
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception:

        logger.exception(
            "Failed to load vendor profile. "
            "vendor_id=%s",
            vendor_id,
        )

        raise _database_error() from None

    if not rows:
        raise _profile_not_found()

    return rows[0]


# ============================================================
# UPDATE VENDOR PROFILE
#
# PATCH /api/v1/vendor/profile
#
# Direct modification is disabled.
#
# All business information changes, including
# email and phone, require Admin approval.
#
# The existing route remains registered for
# compatibility but cannot mutate vendor data.
# ============================================================

def update_vendor_profile(
    vendor_id: str,
    payload: dict,
) -> dict:

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid business profile data.",
        )

    if not payload:
        return get_vendor_profile(
            vendor_id=vendor_id,
        )

    submitted_fields = set(payload.keys())

    if submitted_fields & BRANDING_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Logo and banner changes must be "
                "uploaded through the Branding API."
            ),
        )

    if submitted_fields & APPROVAL_REQUIRED_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "All business profile information "
                "changes require Admin approval, "
                "including email and phone number. "
                "Submit a Business Profile Change Request."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "One or more fields cannot be updated "
            "through the Business Profile API."
        ),
    )

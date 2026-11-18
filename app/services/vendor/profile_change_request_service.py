
"""
AUMVEDA Vendor Backend
Business Profile Change Request Service

Purpose:
- Submit business profile changes for Admin approval.
- List vendor-specific change requests.
- Retrieve individual change requests.
- Prevent duplicate pending requests.
- Preserve existing approved vendor information.

Approval-required sections:
1. store_information
2. business_address
3. legal_tax

Immediate updates handled separately:
- Contact information
- Logo
- Banner

Security:
- Vendor ID comes from authenticated context.
- Submitted-by ID comes from authenticated context.
- API routes must use get_vendor_owner.
- Only section-approved fields are accepted.
- Vendor approval status cannot be changed.
- Commission rate cannot be changed.
- No direct updates to public.vendors.
- Database errors are not exposed to clients.
"""

import logging

from uuid import UUID

from fastapi import (
    HTTPException,
    status,
)

from app.core.supabase import (
    supabase_admin,
)

from app.schemas.vendor.profile_change_requests import (
    PROFILE_CHANGE_ALLOWED_FIELDS,
    VendorProfileChangeCreateRequest,
    VendorProfileChangeSection,
)


# ============================================================
# LOGGER
# ============================================================

logger = logging.getLogger(
    "aumveda.vendor.profile_change_requests"
)


# ============================================================
# DATABASE TABLE
# ============================================================

CHANGE_REQUEST_TABLE = (
    "vendor_profile_change_requests"
)


# ============================================================
# ERROR HELPERS
# ============================================================

def _database_error() -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE
        ),
        detail=(
            "Unable to process business profile "
            "change requests at this time."
        ),
    )


def _request_not_found() -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_404_NOT_FOUND
        ),
        detail=(
            "Business profile change request "
            "was not found."
        ),
    )


def _validation_error(
    message: str,
) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_422_UNPROCESSABLE_ENTITY
        ),
        detail=message,
    )


def _pending_conflict() -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_409_CONFLICT
        ),
        detail=(
            "A pending change request already exists "
            "for this business section. "
            "Please wait for Admin review."
        ),
    )


# ============================================================
# UUID VALIDATION
# ============================================================

def _normalize_uuid(
    value,
) -> str:

    try:
        return str(
            UUID(str(value))
        )

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        raise _validation_error(
            "Invalid business profile identifier."
        ) from None


# ============================================================
# DATABASE ERROR LOGGING
# ============================================================

def _log_database_error(
    operation: str,
    exc: Exception,
) -> None:

    logger.error(
        "Business profile request operation failed: %s",
        operation,
        exc_info=(
            type(exc),
            exc,
            exc.__traceback__,
        ),
    )


# ============================================================
# VERIFY VENDOR BUSINESS
#
# The API must already have authenticated an
# approved Vendor Owner.
#
# This additional check ensures the vendor
# still exists, is approved and is active.
# ============================================================

def _verify_vendor(
    vendor_id: str,
) -> dict:

    try:
        response = (
            supabase_admin
            .table("vendors")
            .select(
                "id,status,is_active"
            )
            .eq(
                "id",
                vendor_id,
            )
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception as exc:
        _log_database_error(
            "verify vendor",
            exc,
        )
        raise _database_error() from None

    if not rows:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail="Vendor business was not found.",
        )

    vendor = rows[0]

    if (
        str(
            vendor.get("status") or ""
        ).lower() != "approved"
        or vendor.get("is_active") is not True
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "Only approved and active vendors "
                "can submit business profile changes."
            ),
        )

    return vendor


# ============================================================
# VALIDATE CHANGE REQUEST
#
# Schema validation happens before the service.
# This service repeats the field allowlist check
# as defense in depth.
# ============================================================

def _validate_request_fields(
    payload: VendorProfileChangeCreateRequest,
) -> dict:

    section = payload.section

    allowed_fields = (
        PROFILE_CHANGE_ALLOWED_FIELDS[
            section
        ]
    )

    changes = dict(
        payload.proposed_changes
    )

    if not changes:
        raise _validation_error(
            "At least one business field must be changed."
        )

    invalid_fields = (
        set(changes.keys()) - allowed_fields
    )

    if invalid_fields:
        raise _validation_error(
            "Invalid fields for the selected "
            "business profile section."
        )

    if (
        section ==
        VendorProfileChangeSection.STORE_INFORMATION
    ):
        if (
            "business_name" in changes
            and not str(
                changes["business_name"]
            ).strip()
        ):
            raise _validation_error(
                "Business name cannot be empty."
            )

    return changes


# ============================================================
# CHECK EXISTING PENDING REQUEST
#
# Database unique partial index also prevents
# duplicate pending requests during races.
# ============================================================

def _get_pending_request(
    vendor_id: str,
    section: str,
) -> dict | None:

    try:
        response = (
            supabase_admin
            .table(
                CHANGE_REQUEST_TABLE
            )
            .select("*")
            .eq(
                "vendor_id",
                vendor_id,
            )
            .eq(
                "section",
                section,
            )
            .eq(
                "status",
                "pending",
            )
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception as exc:
        _log_database_error(
            "check pending request",
            exc,
        )
        raise _database_error() from None

    if rows:
        return rows[0]

    return None


# ============================================================
# SUBMIT BUSINESS PROFILE CHANGE REQUEST
#
# POST /api/v1/vendor/profile/change-requests
#
# Does NOT update public.vendors.
#
# Admin Backend will perform the approved changes
# in a separate, atomic review transaction.
# ============================================================

def create_vendor_profile_change_request(
    *,
    vendor_id: str,
    submitted_by: str,
    payload: VendorProfileChangeCreateRequest,
) -> dict:

    normalized_vendor_id = (
        _normalize_uuid(vendor_id)
    )

    normalized_user_id = (
        _normalize_uuid(submitted_by)
    )

    # --------------------------------------------------------
    # 1. VALIDATE THE APPROVED VENDOR
    # --------------------------------------------------------

    _verify_vendor(
        normalized_vendor_id
    )

    # --------------------------------------------------------
    # 2. VALIDATE SECTION AND CHANGES
    # --------------------------------------------------------

    section = payload.section.value

    proposed_changes = (
        _validate_request_fields(
            payload
        )
    )

    # --------------------------------------------------------
    # 3. CHECK DUPLICATE PENDING REQUEST
    # --------------------------------------------------------

    existing_pending = (
        _get_pending_request(
            vendor_id=normalized_vendor_id,
            section=section,
        )
    )

    if existing_pending:
        raise _pending_conflict()

    # --------------------------------------------------------
    # 4. PREPARE REQUEST
    #
    # Never accept these values from the frontend:
    # - vendor_id
    # - submitted_by
    # - status
    # - reviewed_by
    # - reviewed_at
    # --------------------------------------------------------

    request_data = {
        "vendor_id": normalized_vendor_id,
        "submitted_by": normalized_user_id,
        "section": section,
        "proposed_changes": proposed_changes,
        "status": "pending",
    }

    # --------------------------------------------------------
    # 5. SAVE THE PENDING REQUEST
    # --------------------------------------------------------

    try:
        response = (
            supabase_admin
            .table(
                CHANGE_REQUEST_TABLE
            )
            .insert(
                request_data
            )
            .execute()
        )

        rows = response.data or []

    except Exception as exc:

        # PostgreSQL unique-constraint violation.
        # Handles concurrent duplicate submissions.

        error_code = (
            getattr(
                exc,
                "code",
                None,
            )
            or getattr(
                exc,
                "sqlstate",
                None,
            )
        )

        if str(error_code) == "23505":
            raise _pending_conflict() from None

        _log_database_error(
            "create business profile change request",
            exc,
        )

        raise _database_error() from None

    if not rows:
        logger.error(
            "Profile change request insert returned "
            "no data for vendor_id=%s",
            normalized_vendor_id,
        )

        raise _database_error()

    created_request = rows[0]

    # --------------------------------------------------------
    # 6. RETURN SUCCESS
    #
    # Business details remain unchanged.
    # --------------------------------------------------------

    return {
        "status": "success",
        "message": (
            "Your business profile change request "
            "has been submitted for Admin approval. "
            "Your existing business information "
            "will remain unchanged until approval."
        ),
        "request": created_request,
    }


# ============================================================
# LIST VENDOR BUSINESS PROFILE CHANGE REQUESTS
#
# GET /api/v1/vendor/profile/change-requests
#
# Owner-only API.
# Includes pending, approved and rejected requests.
# ============================================================

def list_vendor_profile_change_requests(
    vendor_id: str,
) -> dict:

    normalized_vendor_id = (
        _normalize_uuid(vendor_id)
    )

    try:
        response = (
            supabase_admin
            .table(
                CHANGE_REQUEST_TABLE
            )
            .select("*")
            .eq(
                "vendor_id",
                normalized_vendor_id,
            )
            .order(
                "created_at",
                desc=True,
            )
            .execute()
        )

        rows = response.data or []

    except Exception as exc:
        _log_database_error(
            "list business profile change requests",
            exc,
        )

        raise _database_error() from None

    return {
        "requests": rows,
        "total": len(rows),
    }


# ============================================================
# GET INDIVIDUAL BUSINESS PROFILE CHANGE REQUEST
#
# GET /api/v1/vendor/profile/change-requests/{id}
#
# Uses BOTH vendor_id and request_id.
# Prevents cross-vendor request retrieval.
# ============================================================

def get_vendor_profile_change_request(
    *,
    vendor_id: str,
    request_id: str,
) -> dict:

    normalized_vendor_id = (
        _normalize_uuid(vendor_id)
    )

    normalized_request_id = (
        _normalize_uuid(request_id)
    )

    try:
        response = (
            supabase_admin
            .table(
                CHANGE_REQUEST_TABLE
            )
            .select("*")
            .eq(
                "vendor_id",
                normalized_vendor_id,
            )
            .eq(
                "id",
                normalized_request_id,
            )
            .limit(1)
            .execute()
        )

        rows = response.data or []

    except Exception as exc:
        _log_database_error(
            "get business profile change request",
            exc,
        )

        raise _database_error() from None

    if not rows:
        raise _request_not_found()

    return rows[0]

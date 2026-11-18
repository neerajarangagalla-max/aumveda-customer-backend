
"""
AUMVEDA Vendor Backend
Business Profile Change Request Schemas

STEP 19.9.11

Purpose:
- Validate business profile change requests.
- Enforce section-specific allowed fields.
- Require Admin approval for all business information.
- Prevent changes to system-managed properties.
- Validate Business Email and Phone Number.
- Preserve approved vendor information until approval.

Approval-required sections:
1. Store Information
2. Contact Information
3. Business Address
4. Legal & Tax Details

Immediate changes:
- Store Logo
- Store Banner

Security:
- vendor_id comes from authentication.
- submitted_by comes from authentication.
- Request status is backend-managed.
- Admin review fields cannot be submitted by vendors.
"""

from datetime import datetime
from enum import Enum
from typing import Dict
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)


# ============================================================
# CHANGE REQUEST SECTIONS
# ============================================================

class VendorProfileChangeSection(str, Enum):

    STORE_INFORMATION = "store_information"

    CONTACT_INFORMATION = "contact_information"

    BUSINESS_ADDRESS = "business_address"

    LEGAL_TAX = "legal_tax"


# ============================================================
# ALLOWED FIELDS FOR EACH SECTION
# ============================================================

PROFILE_CHANGE_ALLOWED_FIELDS = {

    VendorProfileChangeSection.STORE_INFORMATION: {
        "business_name",
        "description",
    },

    VendorProfileChangeSection.CONTACT_INFORMATION: {
        "email",
        "phone",
    },

    VendorProfileChangeSection.BUSINESS_ADDRESS: {
        "address_line1",
        "address_line2",
        "city",
        "state",
        "postal_code",
        "country",
    },

    VendorProfileChangeSection.LEGAL_TAX: {
        "legal_name",
        "tax_id",
    },
}


# ============================================================
# CHANGE REQUEST STATUS
# ============================================================

class VendorProfileChangeStatus(str, Enum):

    PENDING = "pending"

    APPROVED = "approved"

    REJECTED = "rejected"


# ============================================================
# FIELD LENGTH LIMITS
#
# These are API validation limits.
# Actual PostgreSQL column constraints must also
# be checked before enabling live submissions.
# ============================================================

PROFILE_FIELD_MAX_LENGTHS = {

    "business_name": 200,
    "description": 2000,

    "email": 254,
    "phone": 30,

    "address_line1": 255,
    "address_line2": 255,

    "city": 120,
    "state": 120,

    "postal_code": 30,
    "country": 120,

    "legal_name": 255,
    "tax_id": 100,
}


# ============================================================
# EMAIL VALIDATOR
#
# Uses Pydantic's EmailStr validator.
# ============================================================

email_adapter = TypeAdapter(EmailStr)


# ============================================================
# SUBMIT CHANGE REQUEST
#
# POST /api/v1/vendor/profile/change-requests
#
# Example:
#
# {
#     "section": "contact_information",
#     "proposed_changes": {
#         "email": "support@example.com",
#         "phone": "9876543210"
#     }
# }
# ============================================================

class VendorProfileChangeCreateRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
    )

    section: VendorProfileChangeSection

    proposed_changes: Dict[str, str] = Field(
        ...,
        min_length=1,
        max_length=6,
    )

    # --------------------------------------------------------
    # VALIDATE CHANGE REQUEST
    # --------------------------------------------------------

    @model_validator(mode="after")
    def validate_proposed_changes(self):

        allowed_fields = (
            PROFILE_CHANGE_ALLOWED_FIELDS[
                self.section
            ]
        )

        submitted_fields = set(
            self.proposed_changes.keys()
        )

        # ----------------------------------------------------
        # BLOCK FIELDS BELONGING TO OTHER SECTIONS
        # ----------------------------------------------------

        invalid_fields = (
            submitted_fields - allowed_fields
        )

        if invalid_fields:

            raise ValueError(
                "One or more fields are not allowed "
                "for the selected business section."
            )

        normalized_changes = {}

        # ----------------------------------------------------
        # VALIDATE EACH SUBMITTED FIELD
        # ----------------------------------------------------

        for field_name, field_value in (
            self.proposed_changes.items()
        ):

            if not isinstance(
                field_value,
                str,
            ):

                raise ValueError(
                    "Business profile values "
                    "must be strings."
                )

            normalized_value = (
                field_value.strip()
            )

            # ------------------------------------------------
            # BUSINESS NAME
            #
            # Business name cannot be cleared.
            # ------------------------------------------------

            if field_name == "business_name":

                if not normalized_value:

                    raise ValueError(
                        "Business name cannot be empty."
                    )

            # ------------------------------------------------
            # EMAIL VALIDATION
            #
            # Changing business email requires
            # Admin approval.
            #
            # Empty email is permitted only when
            # the database/business policy allows
            # clearing that optional field.
            # ------------------------------------------------

            if field_name == "email":

                if normalized_value:

                    try:

                        normalized_value = (
                            email_adapter.validate_python(
                                normalized_value
                            )
                        )

                    except ValidationError:

                        raise ValueError(
                            "Enter a valid business "
                            "email address."
                        ) from None

            # ------------------------------------------------
            # PHONE VALIDATION
            #
            # Reject control characters.
            # Accept phone formatting characters
            # such as +, spaces and hyphens.
            #
            # More specific country-based validation
            # can be introduced if required.
            # ------------------------------------------------

            if field_name == "phone":

                if normalized_value:

                    if any(
                        ord(character) < 32
                        or ord(character) == 127
                        for character in normalized_value
                    ):

                        raise ValueError(
                            "Phone number contains "
                            "invalid characters."
                        )

                    permitted = set(
                        "0123456789+-() ."
                    )

                    if any(
                        character not in permitted
                        for character in normalized_value
                    ):

                        raise ValueError(
                            "Phone number contains "
                            "unsupported characters."
                        )

                    digit_count = sum(
                        character.isdigit()
                        for character in normalized_value
                    )

                    if not 7 <= digit_count <= 15:

                        raise ValueError(
                            "Phone number must contain "
                            "between 7 and 15 digits."
                        )

            # ------------------------------------------------
            # FIELD LENGTH VALIDATION
            # ------------------------------------------------

            max_length = (
                PROFILE_FIELD_MAX_LENGTHS.get(
                    field_name,
                    200,
                )
            )

            if len(normalized_value) > max_length:

                raise ValueError(
                    f"{field_name} exceeds "
                    f"the maximum length of "
                    f"{max_length} characters."
                )

            # ------------------------------------------------
            # STORE VALIDATED VALUE
            # ------------------------------------------------

            normalized_changes[
                field_name
            ] = normalized_value

        self.proposed_changes = (
            normalized_changes
        )

        return self


# ============================================================
# RESPONSE SCHEMA
#
# Represents a saved business profile
# change request.
# ============================================================

class VendorProfileChangeResponse(BaseModel):

    model_config = ConfigDict(
        extra="ignore",
    )

    id: UUID

    vendor_id: UUID

    submitted_by: UUID

    section: VendorProfileChangeSection

    proposed_changes: Dict[str, str]

    status: VendorProfileChangeStatus

    reviewed_by: UUID | None = None

    reviewed_at: datetime | None = None

    rejection_reason: str | None = None

    created_at: datetime

    updated_at: datetime


# ============================================================
# SUBMISSION RESPONSE
# ============================================================

class VendorProfileChangeSubmitResponse(BaseModel):

    status: str

    message: str

    request: VendorProfileChangeResponse


# ============================================================
# REQUEST LIST RESPONSE
# ============================================================

class VendorProfileChangeListResponse(BaseModel):

    requests: list[
        VendorProfileChangeResponse
    ]

    total: int

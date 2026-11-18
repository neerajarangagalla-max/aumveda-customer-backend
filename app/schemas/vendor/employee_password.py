
"""
AUMVEDA Vendor Backend
Employee Password Management Schemas

The Vendor Owner chooses a new employee password.

The password is never stored in application tables
or returned in API responses.

Supabase Auth enforces its configured password policy.
"""

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
)


class VendorEmployeePasswordResetRequest(BaseModel):
    new_password: SecretStr = Field(
        ...,
        description=(
            "New password selected by the Vendor Owner. "
            "Must be nonempty. Supabase Auth enforces "
            "the configured password policy."
        ),
    )


class VendorEmployeePasswordResetResponse(BaseModel):
    status: str

    message: str

    user_id: str

    password_updated: bool

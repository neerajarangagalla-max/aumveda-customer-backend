
"""
AUMVEDA Vendor Backend
Owner-Created Employee Account Schemas
"""

from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)


class VendorStaffCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    full_name: str = Field(
        min_length=2,
        max_length=150,
    )

    email: EmailStr

    password: SecretStr

    role_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.split())

        if not 2 <= len(name) <= 150:
            raise ValueError(
                "Employee name must contain "
                "2 to 150 characters."
            )

        return name

    @field_validator("password")
    @classmethod
    def validate_password(
        cls,
        value: SecretStr,
    ) -> SecretStr:
        password = value.get_secret_value()

        if not password:
            raise ValueError(
                "Employee password cannot be empty."
            )

        return value

    @field_validator("role_ids")
    @classmethod
    def validate_role_ids(
        cls,
        value: list[UUID],
    ) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError(
                "Duplicate custom roles are not allowed."
            )

        return value


class VendorStaffCreateResponse(BaseModel):
    status: str
    message: str
    staff: dict
    account_status: str


from uuid import UUID

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    field_validator,
)


class VendorStaffInvitationRequest(BaseModel):
    full_name: str = Field(
        min_length=2,
        max_length=150,
    )

    email: EmailStr

    role_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = " ".join(value.split())

        if len(name) < 2:
            raise ValueError(
                "Staff name must contain at least "
                "two characters."
            )

        return name

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

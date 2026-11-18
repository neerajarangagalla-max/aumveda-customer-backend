
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    field_validator,
)


# ============================================================
# AUMVEDA VENDOR TEAM SCHEMAS
# ============================================================


# ============================================================
# UPDATE SYSTEM MEMBER ROLE
#
# Owner is deliberately excluded.
#
# Existing Vendor Owners retain their ownership.
# New owners cannot be created through this API.
# ============================================================

class VendorMemberRoleUpdateRequest(BaseModel):
    member_role: Literal[
        "manager",
        "staff",
        "inventory",
        "orders",
    ]


# ============================================================
# ACTIVATE / DEACTIVATE MEMBER
# ============================================================

class VendorMemberStatusUpdateRequest(BaseModel):
    is_active: bool


# ============================================================
# ASSIGN CUSTOM ROLES
#
# Supports multiple reusable roles.
# ============================================================

class VendorMemberCustomRolesRequest(BaseModel):
    role_ids: list[UUID] = Field(
        min_length=1,
        max_length=100,
    )

    @field_validator("role_ids")
    @classmethod
    def validate_role_ids(
        cls,
        role_ids: list[UUID],
    ) -> list[UUID]:
        if len(role_ids) != len(set(role_ids)):
            raise ValueError(
                "Duplicate custom role IDs are not allowed."
            )

        return role_ids

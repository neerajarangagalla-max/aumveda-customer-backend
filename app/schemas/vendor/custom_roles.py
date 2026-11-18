
from typing import Literal

from pydantic import BaseModel, Field


VendorPermissionKey = Literal[
    "dashboard.view",

    "products.view",
    "products.create",
    "products.update",
    "products.images",

    "inventory.view",
    "inventory.update",

    "orders.view",
    "orders.update",

    "shipping.view",
    "shipping.update",
    "earnings.view",
]


# ============================================================
# CREATE CUSTOM ROLE
# ============================================================

class VendorCustomRoleCreateRequest(BaseModel):
    role_name: str = Field(
        min_length=2,
        max_length=80,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    permissions: list[VendorPermissionKey] = Field(
        min_length=1,
        max_length=11,
    )


# ============================================================
# UPDATE CUSTOM ROLE
#
# Fields are optional for partial updates.
# Explicit null description clears the description.
# ============================================================

class VendorCustomRoleUpdateRequest(BaseModel):
    role_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=80,
    )

    description: str | None = Field(
        default=None,
        max_length=500,
    )

    permissions: list[VendorPermissionKey] | None = Field(
        default=None,
        min_length=1,
        max_length=11,
    )


# ============================================================
# ACTIVATE / DEACTIVATE CUSTOM ROLE
# ============================================================

class VendorCustomRoleStatusRequest(BaseModel):
    is_active: bool

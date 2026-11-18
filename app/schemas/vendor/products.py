
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# PRODUCT SCHEMAS
# ============================================================


class VendorProductCreateRequest(BaseModel):
    category_id: str
    formulation_id: str | None = None

    name: str = Field(
        min_length=2,
        max_length=200,
    )

    short_description: str | None = None
    description: str | None = None

    ingredients: str | None = None
    benefits: str | None = None
    directions: str | None = None
    warnings: str | None = None


class VendorProductUpdateRequest(BaseModel):
    # Vendors may update product information,
    # but may not change approval status.
    model_config = ConfigDict(extra="forbid")

    category_id: str | None = None
    formulation_id: str | None = None

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    short_description: str | None = None
    description: str | None = None

    ingredients: str | None = None
    benefits: str | None = None
    directions: str | None = None
    warnings: str | None = None


# ============================================================
# PRODUCT VARIANT SCHEMAS
# ============================================================


class VendorVariantCreateRequest(BaseModel):
    name: str | None = None

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    size_value: Decimal | None = None
    size_unit: str | None = None

    price: Decimal = Field(
        gt=0
    )

    compare_at_price: Decimal | None = None
    cost_price: Decimal | None = None

    stock_quantity: int = Field(
        default=0,
        ge=0,
    )

    low_stock_threshold: int = Field(
        default=5,
        ge=0,
    )

    is_default: bool = False
    is_active: bool = True


class VendorVariantUpdateRequest(BaseModel):
    name: str | None = None

    sku: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    size_value: Decimal | None = None
    size_unit: str | None = None

    price: Decimal | None = Field(
        default=None,
        gt=0,
    )

    compare_at_price: Decimal | None = None
    cost_price: Decimal | None = None

    stock_quantity: int | None = Field(
        default=None,
        ge=0,
    )

    low_stock_threshold: int | None = Field(
        default=None,
        ge=0,
    )

    is_default: bool | None = None
    is_active: bool | None = None

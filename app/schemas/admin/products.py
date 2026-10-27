
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

ProductStatus = Literal[
    "draft", "pending", "active", "rejected", "archived"
]


class AdminProductVariantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = None
    name: str | None = None
    price: float = Field(ge=0)
    compare_at_price: float | None = Field(default=None, ge=0)
    cost_price: float | None = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_compare_price(self):
        if (
            self.compare_at_price is not None
            and self.compare_at_price < self.price
        ):
            raise ValueError(
                "Compare-at price must be greater than or equal to price"
            )
        return self


class AdminProductImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_url: str = Field(min_length=1, max_length=2048)
    alt_text: str | None = None
    sort_order: int = Field(default=0, ge=0)
    is_primary: bool = False

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith(("https://", "http://")):
            raise ValueError(
                "Image URL must start with http:// or https://"
            )
        return value


class ProductFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)

    short_description: str | None = None
    description: str | None = None
    ingredients: str | None = None
    benefits: str | None = None
    directions: str | None = None
    warnings: str | None = None

    status: ProductStatus = "draft"
    is_featured: bool = False


class AdminProductCreate(ProductFields):
    vendor_id: str

    variants: list[AdminProductVariantCreate] = Field(
        default_factory=list
    )
    images: list[AdminProductImageCreate] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_primary_image(self):
        if sum(image.is_primary for image in self.images) > 1:
            raise ValueError("Only one image can be marked as primary")
        return self


class AdminProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=255)

    short_description: str | None = None
    description: str | None = None
    ingredients: str | None = None
    benefits: str | None = None
    directions: str | None = None
    warnings: str | None = None

    status: ProductStatus | None = None
    is_featured: bool | None = None

    variants: list[AdminProductVariantCreate] | None = None
    images: list[AdminProductImageCreate] | None = None

    @model_validator(mode="after")
    def validate_primary_image(self):
        if self.images is not None:
            if sum(image.is_primary for image in self.images) > 1:
                raise ValueError(
                    "Only one image can be marked as primary"
                )
        return self

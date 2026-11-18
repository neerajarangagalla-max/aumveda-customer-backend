from typing import Literal

from pydantic import BaseModel, Field


class VendorInventoryUpdateRequest(BaseModel):
    operation: Literal[
        "set",
        "increase",
        "decrease",
    ]

    quantity: int = Field(
        ge=0,
    )

    low_stock_threshold: int | None = Field(
        default=None,
        ge=0,
    )
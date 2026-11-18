from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class VendorOrderItemStatusUpdateRequest(BaseModel):

    status: Literal[
        "pending",
        "accepted",
        "packed",
        "shipped",
        "delivered",
        "cancelled",
        "returned",
        "refunded",
    ]


class VendorBulkOrderStatusUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "accepted",
        "packed",
    ]

    order_item_ids: list[UUID] = Field(
        default_factory=list,
        max_length=500,
    )

    all_items: bool = False

    @model_validator(mode="after")
    def validate_items(self):

        if self.all_items and self.order_item_ids:
            raise ValueError(
                "Choose all items or selected items, "
                "not both."
            )

        if not self.all_items and not self.order_item_ids:
            raise ValueError(
                "Select at least one order item."
            )

        if len(set(self.order_item_ids)) != len(
            self.order_item_ids
        ):
            raise ValueError(
                "Duplicate order item IDs are not allowed."
            )

        return self
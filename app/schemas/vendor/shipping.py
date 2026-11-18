from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class VendorShipmentCreateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    # Existing single-item shipment support.
    order_item_id: UUID | None = None

    # New combined shipment support.
    order_id: UUID | None = None

    order_item_ids: list[UUID] = Field(
        default_factory=list,
        max_length=500,
    )

    awb_source: Literal[
        "automatic",
        "manual",
    ] = "automatic"

    awb_number: str | None = Field(
        default=None,
        max_length=200,
    )

    courier_name: str | None = Field(
        default=None,
        max_length=150,
    )

    @model_validator(mode="after")
    def validate_shipment(self):

        if self.order_item_id and self.order_item_ids:
            raise ValueError(
                "Provide order_item_id or "
                "order_item_ids, not both."
            )

        if not self.order_item_id and not self.order_item_ids:
            raise ValueError(
                "Select at least one product."
            )

        if self.order_item_ids and not self.order_id:
            raise ValueError(
                "Order ID is required for "
                "combined shipment creation."
            )

        if len(set(self.order_item_ids)) != len(
            self.order_item_ids
        ):
            raise ValueError(
                "Duplicate products are not allowed."
            )

        self.awb_number = (
            self.awb_number or ""
        ).strip() or None

        self.courier_name = (
            self.courier_name or ""
        ).strip() or None

        if self.awb_source == "manual":

            if (
                not self.awb_number
                or not 3 <= len(self.awb_number) <= 200
            ):
                raise ValueError(
                    "Manual courier AWB must contain "
                    "3 to 200 characters."
                )

            if (
                not self.courier_name
                or not 2 <= len(self.courier_name) <= 150
            ):
                raise ValueError(
                    "Courier name must contain "
                    "2 to 150 characters for manual AWB."
                )

        elif self.awb_number:
            raise ValueError(
                "Do not provide an AWB when "
                "automatic generation is selected."
            )

        return self


class VendorShipmentStatusUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "shipped",
        "in_transit",
        "out_for_delivery",
        "delivered",
    ]

    courier_name: str | None = Field(
        default=None,
        max_length=150,
    )

    # Retained for backward compatibility.
    # AWB remains the only tracking number.
    tracking_number: str | None = Field(
        default=None,
        max_length=200,
    )
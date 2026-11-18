from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


class VendorReturnNotesRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )


class VendorReturnPickupRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    pickup_scheduled_at: datetime

    courier_name: str = Field(
        min_length=2,
        max_length=150,
    )

    awb_source: Literal[
        "automatic",
        "manual",
    ] = "automatic"

    awb_number: str | None = Field(
        default=None,
        max_length=200,
    )

    vendor_notes: str | None = Field(
        default=None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_pickup(self):

        if (
            self.pickup_scheduled_at.tzinfo is None
            or self.pickup_scheduled_at.utcoffset() is None
        ):
            raise ValueError(
                "Pickup date must include a timezone."
            )

        self.courier_name = self.courier_name.strip()

        if len(self.courier_name) < 2:
            raise ValueError(
                "Courier name is required."
            )

        self.awb_number = (
            self.awb_number or ""
        ).strip() or None

        if self.awb_source == "manual":

            if (
                not self.awb_number
                or len(self.awb_number) < 3
            ):
                raise ValueError(
                    "Manual AWB must contain "
                    "at least 3 characters."
                )

        elif self.awb_number:

            raise ValueError(
                "Do not provide an AWB for "
                "automatic generation."
            )

        return self


class VendorReturnStatusUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "picked_up",
        "in_transit",
        "exchange_handover_completed",
        "item_received",
        "quality_verified",
        "quality_review_required",
    ]

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_quality_notes(self):

        if self.notes:
            self.notes = self.notes.strip() or None

        if (
            self.status == "quality_review_required"
            and not self.notes
        ):
            raise ValueError(
                "Quality inspection notes are required."
            )

        return self
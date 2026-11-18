
import logging
from uuid import UUID

from fastapi import HTTPException

from app.core.supabase import supabase_admin


logger = logging.getLogger(__name__)


def _uuid(value, field):
    try:
        return str(UUID(str(value)))
    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field}.",
        )


def advance_vendor_shipment(
    vendor_id: str,
    shipment_id: str,
    new_status: str,
    courier_name: str | None = None,
    tracking_number: str | None = None,
):
    """
    Advance a vendor-owned shipment using the
    existing atomic PostgreSQL RPC.

    Allowed transitions:

    ready -> shipped
    shipped -> in_transit
    in_transit -> out_for_delivery
    out_for_delivery -> delivered

    awb_number is the authoritative tracking ID.

    The existing tracking_number RPC parameter is
    retained for compatibility with the database
    function, not as an independent identifier.
    """

    vendor_id = _uuid(
        vendor_id,
        "vendor ID",
    )

    shipment_id = _uuid(
        shipment_id,
        "shipment ID",
    )

    new_status = str(
        new_status or ""
    ).strip().lower()

    transitions = {
        "ready": "shipped",
        "shipped": "in_transit",
        "in_transit": "out_for_delivery",
        "out_for_delivery": "delivered",
    }

    if new_status not in transitions.values():
        raise HTTPException(
            status_code=400,
            detail="Unsupported shipping status.",
        )

    # --------------------------------------------------------
    # VERIFY SHIPMENT OWNERSHIP
    # --------------------------------------------------------

    try:
        response = (
            supabase_admin
            .table("shipments")
            .select(
                "id,order_id,vendor_id,status,"
                "courier_name,tracking_number,awb_number"
            )
            .eq("id", shipment_id)
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

    except Exception as exc:
        logger.exception(
            "Unable to load vendor shipment"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to load shipment.",
        ) from exc

    rows = response.data or []

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Shipment not found.",
        )

    shipment = rows[0]
    current_status = shipment["status"]

    # --------------------------------------------------------
    # VERIFY TRANSITION
    # --------------------------------------------------------

    if (
        transitions.get(current_status)
        != new_status
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Invalid shipment transition from "
                f"{current_status} to {new_status}."
            ),
        )

    # --------------------------------------------------------
    # DISPATCH
    # --------------------------------------------------------

    if new_status == "shipped":
        courier_name = (
            courier_name or ""
        ).strip()

        supplied_tracking = (
            tracking_number or ""
        ).strip()

        awb_number = (
            shipment.get("awb_number") or ""
        ).strip()

        if not (
            3 <= len(awb_number) <= 200
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Shipment has no valid AWB. "
                    "Refresh before dispatch."
                ),
            )

        # Old clients may still send tracking_number.
        # Never allow it to differ from the AWB.
        if (
            supplied_tracking
            and supplied_tracking != awb_number
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Tracking number must match "
                    "the shipment AWB."
                ),
            )

        # Existing PostgreSQL RPC expects
        # p_tracking_number. Pass the canonical AWB.
        tracking_number = awb_number

        if not (
            2 <= len(courier_name) <= 150
        ):
            raise HTTPException(
                status_code=400,
                detail="Enter a valid courier name.",
            )

    # --------------------------------------------------------
    # ATOMIC DATABASE UPDATE
    # --------------------------------------------------------

    try:
        response = (
            supabase_admin
            .rpc(
                "vendor_advance_shipment_atomic",
                {
                    "p_vendor_id": vendor_id,
                    "p_shipment_id": shipment_id,
                    "p_new_status": new_status,
                    "p_courier_name": courier_name,
                    "p_tracking_number": tracking_number,
                },
            )
            .execute()
        )

    except Exception as exc:
        logger.exception(
            "Atomic shipment update failed"
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "Shipment update could not be "
                "completed. Refresh shipment "
                "details and verify its "
                "current status."
            ),
        ) from exc

    result = response.data

    if isinstance(result, list):
        result = (
            result[0]
            if result
            else None
        )

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail=(
                "Unexpected shipment update response."
            ),
        )

    # --------------------------------------------------------
    # RETURN THE LATEST SHIPMENT
    # --------------------------------------------------------

    try:
        saved = (
            supabase_admin
            .table("shipments")
            .select("*")
            .eq("id", shipment_id)
            .eq("vendor_id", vendor_id)
            .single()
            .execute()
        )

    except Exception:
        logger.exception(
            "Shipment updated but could not "
            "be reloaded"
        )

        return {
            **result,
            "shipment": None,
        }

    return {
        **result,
        "shipment": saved.data,
    }

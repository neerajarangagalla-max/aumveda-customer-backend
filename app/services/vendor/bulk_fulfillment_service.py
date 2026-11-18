import logging

from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException

from app.core.supabase import supabase_admin

from app.services.vendor.order_service import (
    get_vendor_order,
    get_vendor_order_item,
)

from app.services.vendor.shipping_service import (
    get_vendor_shipment,
)

from app.services.vendor.shipping_tracking_service import (
    advance_vendor_shipment,
)


logger = logging.getLogger(__name__)


# ============================================================
# VALIDATION
# ============================================================

def _validate_uuid(value, field_name: str) -> str:

    try:
        return str(UUID(str(value)))

    except (
        TypeError,
        ValueError,
        AttributeError,
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name}.",
        )


def _normalize_item_ids(
    order_item_ids: list,
) -> list[str]:

    item_ids = [
        _validate_uuid(
            item_id,
            "order item ID",
        )
        for item_id in order_item_ids
    ]

    if len(item_ids) != len(set(item_ids)):
        raise HTTPException(
            status_code=400,
            detail="Duplicate order items are not allowed.",
        )

    return item_ids


def _rpc_result(response) -> dict:

    result = response.data

    if isinstance(result, list):
        result = result[0] if result else None

    if not isinstance(result, dict):
        raise HTTPException(
            status_code=500,
            detail="Unexpected database response.",
        )

    return result


# ============================================================
# LOAD VENDOR ORDER ITEMS
# ============================================================

def _get_order_items(
    vendor_id: str,
    order_id: str,
) -> list[dict]:

    try:

        response = (
            supabase_admin
            .table("order_items")
            .select(
                "id,order_id,vendor_id,"
                "product_name,variant_name,"
                "sku,quantity,status"
            )
            .eq("vendor_id", vendor_id)
            .eq("order_id", order_id)
            .order("created_at")
            .execute()
        )

        items = response.data or []

    except Exception as exc:

        logger.exception(
            "Unable to load vendor order items"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to load vendor order items.",
        ) from exc

    if not items:

        raise HTTPException(
            status_code=404,
            detail="Vendor order not found.",
        )

    return items


# ============================================================
# LOAD SHIPMENT ALLOCATIONS
# ============================================================

def _get_shipment_allocations(
    vendor_id: str,
    order_item_ids: list[str],
) -> dict:

    if not order_item_ids:
        return {}

    try:

        response = (
            supabase_admin
            .table("shipment_items")
            .select(
                "shipment_id,"
                "order_item_id,"
                "quantity"
            )
            .in_(
                "order_item_id",
                order_item_ids,
            )
            .execute()
        )

        links = response.data or []

        if not links:
            return {}

        shipment_ids = list({
            link["shipment_id"]
            for link in links
        })

        shipments_response = (
            supabase_admin
            .table("shipments")
            .select(
                "id,order_id,vendor_id,"
                "status,awb_number,awb_source,"
                "courier_name,tracking_number,"
                "shipped_at,delivered_at"
            )
            .in_("id", shipment_ids)
            .eq("vendor_id", vendor_id)
            .execute()
        )

        shipments_by_id = {
            shipment["id"]: shipment
            for shipment in (
                shipments_response.data or []
            )
        }

        allocations = defaultdict(list)

        for link in links:

            shipment = shipments_by_id.get(
                link["shipment_id"]
            )

            allocations[
                link["order_item_id"]
            ].append({

                "shipment_id":
                    link["shipment_id"],

                "quantity":
                    link["quantity"],

                "status":
                    shipment.get("status")
                    if shipment else None,

                "awb_number":
                    shipment.get("awb_number")
                    if shipment else None,

                "awb_source":
                    shipment.get("awb_source")
                    if shipment else None,

                "courier_name":
                    shipment.get("courier_name")
                    if shipment else None,

            })

        return dict(allocations)

    except Exception as exc:

        logger.exception(
            "Unable to load shipment allocations"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to verify existing "
                "shipment allocations."
            ),
        ) from exc


# ============================================================
# ENHANCED ORDER DETAILS
# ============================================================

def get_vendor_order_fulfillment(
    vendor_id: str,
    order_id: str,
) -> dict:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    order_id = _validate_uuid(
        order_id,
        "order ID",
    )

    order = get_vendor_order(
        vendor_id=vendor_id,
        order_id=order_id,
    )

    items = order.get("items") or []

    allocations = _get_shipment_allocations(
        vendor_id=vendor_id,
        order_item_ids=[
            item["id"]
            for item in items
        ],
    )

    enhanced_items = []

    pending_count = 0
    accepted_count = 0
    packed_count = 0
    ready_to_ship_count = 0
    shipped_count = 0
    delivered_count = 0
    allocated_count = 0

    order_is_active = order.get(
        "order_status"
    ) not in {
        "cancelled",
        "returned",
        "delivered",
    }

    for item in items:

        item_id = item["id"]

        item_status = item.get(
            "status",
            "pending",
        )

        item_allocations = allocations.get(
            item_id,
            [],
        )

        is_allocated = bool(
            item_allocations
        )

        first_shipment = (
            item_allocations[0]
            if item_allocations
            else {}
        )

        allocated_quantity = sum(
            int(
                allocation.get("quantity") or 0
            )
            for allocation in item_allocations
        )

        can_accept = (
            order_is_active
            and item_status == "pending"
            and not is_allocated
        )

        can_pack = (
            order_is_active
            and item_status == "accepted"
            and not is_allocated
        )

        can_move_to_shipping = (
            order_is_active
            and item_status == "packed"
            and not is_allocated
        )

        if item_status == "pending":
            pending_count += 1

        elif item_status == "accepted":
            accepted_count += 1

        elif item_status == "packed":
            packed_count += 1

        elif item_status == "shipped":
            shipped_count += 1

        elif item_status == "delivered":
            delivered_count += 1

        if is_allocated:
            allocated_count += 1

        if can_move_to_shipping:
            ready_to_ship_count += 1

        enhanced_items.append({

            **item,

            "is_allocated": is_allocated,

            "allocated_quantity":
                allocated_quantity,

            "shipment_id":
                first_shipment.get(
                    "shipment_id"
                ),

            "shipment_status":
                first_shipment.get("status"),

            "awb_number":
                first_shipment.get("awb_number"),

            "awb_source":
                first_shipment.get("awb_source"),

            "courier_name":
                first_shipment.get(
                    "courier_name"
                ),

            "shipments":
                item_allocations,

            "can_accept":
                can_accept,

            "can_pack":
                can_pack,

            "can_move_to_shipping":
                can_move_to_shipping,

        })

    return {

        **order,

        "items": enhanced_items,

        "fulfillment_summary": {

            "total_items":
                len(enhanced_items),

            "pending_count":
                pending_count,

            "accepted_count":
                accepted_count,

            "packed_count":
                packed_count,

            "allocated_count":
                allocated_count,

            "ready_to_ship_count":
                ready_to_ship_count,

            "shipped_count":
                shipped_count,

            "delivered_count":
                delivered_count,

            "can_accept_all":
                any(
                    item["can_accept"]
                    for item in enhanced_items
                ),

            "can_pack_all":
                any(
                    item["can_pack"]
                    for item in enhanced_items
                ),

            "can_move_all_to_shipping":
                ready_to_ship_count > 0,

        },

    }


# ============================================================
# BULK ORDER STATUS UPDATE
# ============================================================

def bulk_update_vendor_order_status(
    vendor_id: str,
    order_id: str,
    new_status: str,
    order_item_ids: list | None = None,
    all_items: bool = False,
) -> dict:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    order_id = _validate_uuid(
        order_id,
        "order ID",
    )

    requested_status = str(
        new_status or ""
    ).strip().lower()

    expected_statuses = {
        "accepted": "pending",
        "packed": "accepted",
    }

    if requested_status not in expected_statuses:

        raise HTTPException(
            status_code=400,
            detail=(
                "Bulk updates support accepting "
                "or packing products only."
            ),
        )

    expected_status = expected_statuses[
        requested_status
    ]

    if all_items and order_item_ids:

        raise HTTPException(
            status_code=400,
            detail=(
                "Choose all items or selected "
                "items, not both."
            ),
        )

    order = get_vendor_order_fulfillment(
        vendor_id=vendor_id,
        order_id=order_id,
    )

    if order.get("order_status") in {
        "cancelled",
        "returned",
        "delivered",
    }:

        raise HTTPException(
            status_code=409,
            detail="This order cannot be updated.",
        )

    items = order["items"]

    items_by_id = {
        item["id"]: item
        for item in items
    }

    if all_items:

        # Only update eligible products.
        # Never move advanced items backwards.
        item_ids = [

            item["id"]

            for item in items

            if (
                item.get("status")
                == expected_status
                and not item["is_allocated"]
            )

        ]

    else:

        item_ids = _normalize_item_ids(
            order_item_ids or []
        )

        for item_id in item_ids:

            item = items_by_id.get(
                item_id
            )

            if not item:

                raise HTTPException(
                    status_code=404,
                    detail=(
                        "One or more selected products "
                        "do not belong to this order "
                        "and vendor."
                    ),
                )

            if item["is_allocated"]:

                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A selected product is already "
                        "assigned to a shipment."
                    ),
                )

            if item.get("status") not in {
                expected_status,
                requested_status,
            }:

                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A selected product is not "
                        "eligible for this status update."
                    ),
                )

    if not item_ids:

        raise HTTPException(
            status_code=409,
            detail=(
                "No eligible products are available "
                "for this action."
            ),
        )

    try:

        response = (
            supabase_admin
            .rpc(
                "vendor_bulk_update_order_status_atomic",
                {

                    "p_vendor_id":
                        vendor_id,

                    "p_order_id":
                        order_id,

                    "p_order_item_ids":
                        item_ids,

                    "p_new_status":
                        requested_status,

                },
            )
            .execute()
        )

        return _rpc_result(response)

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Bulk vendor order status update failed"
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "Bulk update could not be completed. "
                "Refresh the order and verify "
                "the selected product statuses."
            ),
        ) from exc


# ============================================================
# CREATE SINGLE OR COMBINED SHIPMENT
# ============================================================

def create_vendor_fulfillment_shipment(
    vendor_id: str,
    order_item_id: str | None = None,
    order_id: str | None = None,
    order_item_ids: list | None = None,
    awb_source: str = "automatic",
    awb_number: str | None = None,
    courier_name: str | None = None,
) -> dict:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    if order_item_id and order_item_ids:

        raise HTTPException(
            status_code=400,
            detail=(
                "Provide a single item or a list "
                "of items, not both."
            ),
        )

    # --------------------------------------------------------
    # BACKWARD COMPATIBILITY
    # --------------------------------------------------------

    if order_item_id:

        order_item_id = _validate_uuid(
            order_item_id,
            "order item ID",
        )

        item = get_vendor_order_item(
            vendor_id=vendor_id,
            order_item_id=order_item_id,
        )

        actual_order_id = _validate_uuid(
            item.get("order_id"),
            "order ID",
        )

        if order_id:

            supplied_order_id = _validate_uuid(
                order_id,
                "order ID",
            )

            if supplied_order_id != actual_order_id:

                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Product does not belong "
                        "to the supplied order."
                    ),
                )

        order_id = actual_order_id

        item_ids = [
            order_item_id
        ]

    else:

        order_id = _validate_uuid(
            order_id,
            "order ID",
        )

        item_ids = _normalize_item_ids(
            order_item_ids or []
        )

    if not item_ids:

        raise HTTPException(
            status_code=400,
            detail="Select at least one product.",
        )

    # --------------------------------------------------------
    # VALIDATE SELECTED PRODUCTS
    # --------------------------------------------------------

    items = _get_order_items(
        vendor_id=vendor_id,
        order_id=order_id,
    )

    items_by_id = {
        item["id"]: item
        for item in items
    }

    for item_id in item_ids:

        item = items_by_id.get(
            item_id
        )

        if not item:

            raise HTTPException(
                status_code=404,
                detail=(
                    "One or more selected products "
                    "do not belong to this order "
                    "and vendor."
                ),
            )

        if item.get("status") != "packed":

            raise HTTPException(
                status_code=409,
                detail=(
                    "All selected products must "
                    "be packed before shipping."
                ),
            )

    existing_allocations = (
        _get_shipment_allocations(
            vendor_id=vendor_id,
            order_item_ids=item_ids,
        )
    )

    if any(
        existing_allocations.get(item_id)
        for item_id in item_ids
    ):

        raise HTTPException(
            status_code=409,
            detail=(
                "One or more selected products "
                "are already assigned to a shipment."
            ),
        )

    # --------------------------------------------------------
    # CREATE ONE SHIPMENT AND ONE AWB
    # --------------------------------------------------------

    try:

        response = (
            supabase_admin
            .rpc(
                "vendor_create_multi_item_shipment_atomic",
                {

                    "p_vendor_id":
                        vendor_id,

                    "p_order_id":
                        order_id,

                    "p_order_item_ids":
                        item_ids,

                    "p_awb_source":
                        awb_source,

                    "p_awb_number":
                        awb_number,

                    "p_courier_name":
                        courier_name,

                },
            )
            .execute()
        )

        result = _rpc_result(
            response
        )

    except HTTPException:
        raise

    except Exception as exc:

        logger.exception(
            "Vendor shipment creation failed"
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "Shipment could not be created. "
                "Verify product availability, "
                "packed status and AWB number."
            ),
        ) from exc

    # Preserve existing single-item response field.

    if len(item_ids) == 1:

        result["order_item_id"] = item_ids[0]

    return {

        **result,

        "order_item_ids":
            item_ids,

        "item_count":
            len(item_ids),

        "is_combined_shipment":
            len(item_ids) > 1,

    }


# ============================================================
# SHIPMENT STATUS UPDATE
# ============================================================

def advance_vendor_fulfillment_shipment(
    vendor_id: str,
    shipment_id: str,
    new_status: str,
    courier_name: str | None = None,
    tracking_number: str | None = None,
) -> dict:

    vendor_id = _validate_uuid(
        vendor_id,
        "vendor ID",
    )

    shipment_id = _validate_uuid(
        shipment_id,
        "shipment ID",
    )

    shipment = get_vendor_shipment(
        vendor_id=vendor_id,
        shipment_id=shipment_id,
    )

    awb_number = str(
        shipment.get("awb_number") or ""
    ).strip()

    supplied_tracking = str(
        tracking_number or ""
    ).strip()

    if supplied_tracking and supplied_tracking != awb_number:

        raise HTTPException(
            status_code=409,
            detail=(
                "Tracking number must match "
                "the shipment AWB."
            ),
        )

    if new_status == "shipped":

        courier_name = (

            courier_name

            or shipment.get("courier_name")

            or ""

        ).strip()

    # The updated SQL function automatically advances
    # every product belonging to this shipment.

    return advance_vendor_shipment(

        vendor_id=vendor_id,

        shipment_id=shipment_id,

        new_status=new_status,

        courier_name=courier_name,

        tracking_number=awb_number or None,

    )
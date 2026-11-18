from fastapi import (
    APIRouter,
    Depends,
    status,
)

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.schemas.vendor.shipping import (
    VendorShipmentCreateRequest,
    VendorShipmentStatusUpdateRequest,
)

from app.services.vendor.shipping_service import (
    list_ready_to_ship_items,
    list_vendor_shipments,
    get_vendor_shipment,
)

from app.services.vendor.bulk_fulfillment_service import (
    create_vendor_fulfillment_shipment,
    advance_vendor_fulfillment_shipment,
)


router = APIRouter(
    prefix="/shipping",
    tags=["Vendor Shipping"],
)


# ============================================================
# READY-TO-SHIP ITEMS
#
# Only packed products that have not
# already been allocated to a shipment.
#
# Permission: shipping.view
# ============================================================

@router.get("/ready-items")
def vendor_ready_to_ship_items(

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return list_ready_to_ship_items(

        vendor_id=
            vendor_context["vendor_id"],

    )


# ============================================================
# LIST SHIPMENTS
#
# Each shipment can contain multiple products.
#
# Permission: shipping.view
# ============================================================

@router.get("")
def vendor_shipments(

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return list_vendor_shipments(

        vendor_id=
            vendor_context["vendor_id"],

    )


# ============================================================
# CREATE SHIPMENT
#
# Supports:
# - Existing single-item shipments
# - Combined multi-item shipments
# - Split shipments
# - Automatic AWB
# - Manual AWB
#
# Permission: shipping.update
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def vendor_create_shipment(

    payload: VendorShipmentCreateRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return create_vendor_fulfillment_shipment(

        vendor_id=
            vendor_context["vendor_id"],

        order_item_id=(
            str(payload.order_item_id)
            if payload.order_item_id
            else None
        ),

        order_id=(
            str(payload.order_id)
            if payload.order_id
            else None
        ),

        order_item_ids=[
            str(item_id)
            for item_id in
            payload.order_item_ids
        ],

        awb_source=
            payload.awb_source,

        awb_number=
            payload.awb_number,

        courier_name=
            payload.courier_name,

    )


# ============================================================
# UPDATE SHIPMENT STATUS
#
# A single update automatically applies
# to every linked product.
#
# ready -> shipped
# shipped -> in_transit
# in_transit -> out_for_delivery
# out_for_delivery -> delivered
#
# Permission: shipping.update
# ============================================================

@router.patch("/{shipment_id}/status")
def vendor_update_shipment_status(

    shipment_id: str,

    payload: VendorShipmentStatusUpdateRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.update"
        )
    ),

):

    return advance_vendor_fulfillment_shipment(

        vendor_id=
            vendor_context["vendor_id"],

        shipment_id=
            shipment_id,

        new_status=
            payload.status,

        courier_name=
            payload.courier_name,

        tracking_number=
            payload.tracking_number,

    )


# ============================================================
# SHIPMENT DETAILS
#
# Returns all products assigned to the shipment.
#
# Permission: shipping.view
# ============================================================

@router.get("/{shipment_id}")
def vendor_shipment_details(

    shipment_id: str,

    vendor_context=Depends(
        require_vendor_permission(
            "shipping.view"
        )
    ),

):

    return get_vendor_shipment(

        vendor_id=
            vendor_context["vendor_id"],

        shipment_id=
            shipment_id,

    )
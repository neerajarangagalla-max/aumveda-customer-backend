from fastapi import (
    APIRouter,
    Depends,
)

from app.dependencies.vendor import (
    get_vendor_owner,
)

from app.dependencies.vendor_permissions import (
    require_vendor_permission,
)

from app.schemas.vendor.orders import (
    VendorOrderItemStatusUpdateRequest,
    VendorBulkOrderStatusUpdateRequest,
)

from app.services.vendor.order_service import (
    get_vendor_order_item,
    get_vendor_order_summary,
    list_vendor_orders,
    update_vendor_order_item_status,
)

from app.services.vendor.bulk_fulfillment_service import (
    get_vendor_order_fulfillment,
    bulk_update_vendor_order_status,
)


router = APIRouter(
    prefix="/orders",
    tags=["Vendor Orders"],
)


# ============================================================
# ORDER SUMMARY
# Owner only
# ============================================================

@router.get("/summary")
def vendor_order_summary(

    vendor_context=Depends(
        get_vendor_owner
    ),

):

    return get_vendor_order_summary(
        vendor_context["vendor_id"]
    )


# ============================================================
# ORDER LIST
# Permission: orders.view
# ============================================================

@router.get("")
def vendor_orders(

    vendor_context=Depends(
        require_vendor_permission(
            "orders.view"
        )
    ),

):

    return list_vendor_orders(
        vendor_context["vendor_id"]
    )


# ============================================================
# ORDER ITEM DETAILS
# Permission: orders.view
# ============================================================

@router.get("/items/{order_item_id}")
def vendor_order_item(

    order_item_id: str,

    vendor_context=Depends(
        require_vendor_permission(
            "orders.view"
        )
    ),

):

    return get_vendor_order_item(

        vendor_id=
            vendor_context["vendor_id"],

        order_item_id=
            order_item_id,

    )


# ============================================================
# INDIVIDUAL ORDER ITEM STATUS
# Permission: orders.update
# ============================================================

@router.patch("/items/{order_item_id}/status")
def vendor_update_order_item_status(

    order_item_id: str,

    payload: VendorOrderItemStatusUpdateRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "orders.update"
        )
    ),

):

    return update_vendor_order_item_status(

        vendor_id=
            vendor_context["vendor_id"],

        order_item_id=
            order_item_id,

        new_status=
            payload.status,

    )


# ============================================================
# BULK ORDER ITEM STATUS
#
# Supports:
# - Accept All
# - Accept Selected
# - Mark All Packed
# - Pack Selected
#
# Permission: orders.update
# ============================================================

@router.patch("/{order_id}/items/status")
def vendor_bulk_order_status(

    order_id: str,

    payload: VendorBulkOrderStatusUpdateRequest,

    vendor_context=Depends(
        require_vendor_permission(
            "orders.update"
        )
    ),

):

    return bulk_update_vendor_order_status(

        vendor_id=
            vendor_context["vendor_id"],

        order_id=
            order_id,

        new_status=
            payload.status,

        order_item_ids=[
            str(item_id)
            for item_id in
            payload.order_item_ids
        ],

        all_items=
            payload.all_items,

    )


# ============================================================
# ENHANCED ORDER DETAILS
#
# Includes shipment allocations and
# available fulfillment actions.
#
# Permission: orders.view
# ============================================================

@router.get("/{order_id}")
def vendor_order_detail(

    order_id: str,

    vendor_context=Depends(
        require_vendor_permission(
            "orders.view"
        )
    ),

):

    return get_vendor_order_fulfillment(

        vendor_id=
            vendor_context["vendor_id"],

        order_id=
            order_id,

    )
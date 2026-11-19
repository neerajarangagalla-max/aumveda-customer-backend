
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app.core.supabase import supabase_admin


# ============================================================
# AUMVEDA VENDOR ORDER SERVICE
#
# ORDERS: pending -> accepted -> packed
#
# SHIPPING: ready -> shipped -> in_transit
#           -> out_for_delivery -> delivered
#
# Direct Orders updates cannot dispatch or deliver.
# ============================================================


ALLOWED_ORDER_ITEM_STATUSES = {
    "pending",
    "accepted",
    "packed",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
    "refunded",
}

ALLOWED_ORDER_ITEM_TRANSITIONS = {
    "pending": {"accepted"},
    "accepted": {"packed"},
    "packed": set(),
    "shipped": set(),
    "delivered": set(),
    "cancelled": set(),
    "returned": set(),
    "refunded": set(),
}

VENDOR_FULFILLMENT_STATUSES = {
    "accepted",
    "packed",
}


def _money(value) -> float:
    try:
        return float(
            Decimal(str(value or 0))
        )
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return 0.0


def _vendor_items_total(items: list[dict]) -> float:
    total = Decimal("0")

    for item in items:
        try:
            total += Decimal(
                str(item.get("total_price") or 0)
            )
        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):
            continue

    return float(
        total.quantize(Decimal("0.01"))
    )


def _vendor_items_quantity(
    items: list[dict],
) -> int:
    return sum(
        int(item.get("quantity") or 0)
        for item in items
    )


def _get_vendor_order_items(
    vendor_id: str,
    order_id: str,
) -> list[dict]:
    try:
        response = (
            supabase_admin
            .table("order_items")
            .select("*")
            .eq("vendor_id", vendor_id)
            .eq("order_id", order_id)
            .order("created_at", desc=False)
            .execute()
        )

        items = response.data or []

        if not items:
            raise HTTPException(
                status_code=404,
                detail="Vendor order was not found.",
            )

        return items

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load vendor order items: "
                f"{exc}"
            ),
        ) from exc


def _get_order(order_id: str) -> dict:
    try:
        response = (
            supabase_admin
            .table("orders")
            .select(
                "id,order_number,customer_id,"
                "shipping_address_id,shipping_address,"
                "billing_address,status,payment_status,"
                "subtotal,discount,coupon_code,shipping,tax,"
                "total_amount,currency,customer_notes,"
                "payment_method,created_at,updated_at"
            )
            .eq("id", order_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Order was not found.",
            )

        return rows[0]

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load order: "
                f"{exc}"
            ),
        ) from exc


def list_vendor_orders(
    vendor_id: str,
) -> list[dict]:
    try:
        response = (
            supabase_admin
            .table("order_items")
            .select(
                "id,order_id,product_id,variant_id,"
                "vendor_id,product_name,variant_name,"
                "sku,quantity,unit_price,total_price,"
                "status,created_at,updated_at"
            )
            .eq("vendor_id", vendor_id)
            .order("created_at", desc=True)
            .execute()
        )

        items = response.data or []

        if not items:
            return []

        grouped_items = defaultdict(list)

        for item in items:
            if item.get("order_id"):
                grouped_items[
                    item["order_id"]
                ].append(item)

        result = []

        for order_id, vendor_items in (
            grouped_items.items()
        ):
            order = _get_order(order_id)

            item_statuses = [
                item.get("status") or "pending"
                for item in vendor_items
            ]

            result.append({
                "order_id": order["id"],
                "order_number": order.get(
                    "order_number"
                ),
                "order_status": order.get(
                    "status"
                ),
                "payment_status": order.get(
                    "payment_status"
                ),
                "payment_method": order.get(
                    "payment_method"
                ),
                "coupon_code": order.get(
                    "coupon_code"
                ),
                "discount": order.get(
                    "discount"
                ),
                "currency": order.get(
                    "currency"
                ),
                "vendor_item_count": len(
                    vendor_items
                ),
                "vendor_quantity":
                    _vendor_items_quantity(
                        vendor_items
                    ),
                "vendor_total":
                    _vendor_items_total(
                        vendor_items
                    ),
                "item_statuses": item_statuses,
                "created_at": order.get(
                    "created_at"
                ),
                "updated_at": order.get(
                    "updated_at"
                ),
            })

        result.sort(
            key=lambda row:
                row.get("created_at") or "",
            reverse=True,
        )

        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load vendor orders: "
                f"{exc}"
            ),
        ) from exc


def get_vendor_order(
    vendor_id: str,
    order_id: str,
) -> dict:
    vendor_items = _get_vendor_order_items(
        vendor_id,
        order_id,
    )

    order = _get_order(order_id)

    return {
        "order_id": order["id"],
        "order_number": order.get(
            "order_number"
        ),
        "order_status": order.get(
            "status"
        ),
        "payment_status": order.get(
            "payment_status"
        ),
        "payment_method": order.get(
            "payment_method"
        ),
        "coupon_code": order.get(
            "coupon_code"
        ),
        "discount": order.get(
            "discount"
        ),
        "currency": order.get(
            "currency"
        ),
        "shipping_address": order.get(
            "shipping_address"
        ),
        "customer_notes": order.get(
            "customer_notes"
        ),
        "vendor_item_count": len(vendor_items),
        "vendor_quantity":
            _vendor_items_quantity(vendor_items),
        "vendor_total":
            _vendor_items_total(vendor_items),
        "items": vendor_items,
        "created_at": order.get(
            "created_at"
        ),
        "updated_at": order.get(
            "updated_at"
        ),
    }


def get_vendor_order_item(
    vendor_id: str,
    order_item_id: str,
) -> dict:
    try:
        response = (
            supabase_admin
            .table("order_items")
            .select("*")
            .eq("id", order_item_id)
            .eq("vendor_id", vendor_id)
            .limit(1)
            .execute()
        )

        rows = response.data or []

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="Order item was not found.",
            )

        return rows[0]

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load order item: "
                f"{exc}"
            ),
        ) from exc


def update_vendor_order_item_status(
    vendor_id: str,
    order_item_id: str,
    new_status: str,
) -> dict:
    """
    Orders endpoint can only:
      pending -> accepted
      accepted -> packed

    The database RPC remains responsible for
    atomic item/parent-order synchronization.
    """

    item = get_vendor_order_item(
        vendor_id,
        order_item_id,
    )

    current_status = str(
        item.get("status") or "pending"
    ).strip().lower()

    requested_status = str(
        new_status or ""
    ).strip().lower()

    if not requested_status:
        raise HTTPException(
            status_code=400,
            detail="New order item status is required.",
        )

    if (
        requested_status
        not in ALLOWED_ORDER_ITEM_STATUSES
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported order item status: "
                f"'{requested_status}'."
            ),
        )

    if (
        requested_status
        not in VENDOR_FULFILLMENT_STATUSES
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Orders can only accept or pack items. "
                "After packing, manage delivery "
                "through Shipping."
            ),
        )

    if current_status != requested_status:
        allowed_next = (
            ALLOWED_ORDER_ITEM_TRANSITIONS.get(
                current_status,
                set(),
            )
        )

        if requested_status not in allowed_next:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot change order item status "
                    f"from '{current_status}' "
                    f"to '{requested_status}'."
                ),
            )

    order_id = item.get("order_id")

    if not order_id:
        raise HTTPException(
            status_code=400,
            detail="Order item has no parent order.",
        )

    parent_order = _get_order(order_id)

    parent_status = str(
        parent_order.get("status") or ""
    ).lower()

    if parent_status in {
        "cancelled",
        "returned",
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot update an order that "
                "has been cancelled or returned."
            ),
        )

    try:
        rpc_response = (
            supabase_admin
            .rpc(
                "vendor_update_order_status_atomic",
                {
                    "p_vendor_id": vendor_id,
                    "p_order_item_id": order_item_id,
                    "p_new_status": requested_status,
                },
            )
            .execute()
        )

        result = rpc_response.data

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
                    "Order synchronization returned "
                    "an unexpected response."
                ),
            )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Unable to synchronize order status: "
                f"{exc}"
            ),
        ) from exc

    updated_item = get_vendor_order_item(
        vendor_id,
        order_item_id,
    )

    return {
        "message": (
            "Order item status updated successfully."
            if result.get("item_changed")
            else "Order status synchronized successfully."
        ),
        "previous_status": result.get(
            "previous_item_status",
            current_status,
        ),
        "new_status": result.get(
            "item_status",
            requested_status,
        ),
        "order_item": updated_item,
        "order_id": result.get(
            "order_id",
            order_id,
        ),
        "order_status": result.get(
            "order_status"
        ),
        "item_changed": result.get(
            "item_changed",
            False,
        ),
        "order_changed": result.get(
            "order_changed",
            False,
        ),
    }


def get_vendor_order_summary(
    vendor_id: str,
) -> dict:
    try:
        response = (
            supabase_admin
            .table("order_items")
            .select(
                "id,order_id,quantity,"
                "total_price,status"
            )
            .eq("vendor_id", vendor_id)
            .execute()
        )

        items = response.data or []

        unique_orders = {
            item["order_id"]
            for item in items
            if item.get("order_id")
        }

        status_counts = {
            "pending": 0,
            "accepted": 0,
            "packed": 0,
            "shipped": 0,
            "delivered": 0,
            "cancelled": 0,
            "returned": 0,
            "refunded": 0,
        }

        for item in items:
            item_status = str(
                item.get("status") or "pending"
            ).strip().lower()

            if item_status in status_counts:
                status_counts[
                    item_status
                ] += 1

        return {
            "total_orders": len(unique_orders),
            "total_order_items": len(items),
            "total_quantity":
                _vendor_items_quantity(items),
            "total_value":
                _vendor_items_total(items),
            "status_counts": status_counts,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Unable to load vendor order summary: "
                f"{exc}"
            ),
        ) from exc

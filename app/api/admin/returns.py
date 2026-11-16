
import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import get_current_admin
from app.core.supabase import supabase
from app.services.customer_notifications import create_customer_notification

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/returns",
    tags=["Admin Returns"],
    dependencies=[Depends(get_current_admin)],
)

ALLOWED_RETURN_STATUSES = {
    "requested",
    "under_review",
    "approved",
    "rejected",
    "pickup_scheduled",
    "item_received",
    "replacement_processing",
    "refund_processing",
    "completed",
    "cancelled",
}

ALLOWED_RETURN_TRANSITIONS = {
    "requested": {"under_review", "approved", "rejected", "cancelled"},
    "under_review": {"approved", "rejected", "cancelled"},
    "approved": {"cancelled"},
    "pickup_scheduled": {"cancelled"},
    "item_received": set(),
    "replacement_processing": set(),
    "refund_processing": {"completed"},
    "rejected": set(),
    "completed": set(),
    "cancelled": set(),
}

PENDING_RETURN_STATUSES = {"requested", "under_review"}



class ReturnStatusUpdate(BaseModel):
    status: Literal[
        "under_review",
        "approved",
        "rejected",
        "pickup_scheduled",
        "item_received",
        "replacement_processing",
        "refund_processing",
        "completed",
        "cancelled",
    ]
    notes: str | None = Field(default=None, max_length=1000)


def ensure_vendor_approval_notification(return_request: dict) -> None:
    return_id = str(return_request["id"])
    order_item_id = str(return_request.get("order_item_id") or "")
    request_type = return_request.get("request_type") or "return"
    is_exchange = request_type == "replacement"
    notification_type = (
        "exchange_request_approved"
        if is_exchange
        else "return_request_approved"
    )

    order_item_result = (
        supabase.table("order_items")
        .select("vendor_id, product_name")
        .eq("id", order_item_id)
        .limit(1)
        .execute()
    )
    order_items = order_item_result.data or []
    vendor_id = order_items[0].get("vendor_id") if order_items else None

    if not vendor_id:
        logger.error(
            "Cannot notify vendor for approved return request %s: "
            "order item has no vendor.",
            return_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to notify the product vendor.",
        )

    members_result = (
        supabase.table("vendor_members")
        .select("user_id")
        .eq("vendor_id", str(vendor_id))
        .eq("is_active", True)
        .execute()
    )
    member_ids = sorted({
        str(member["user_id"])
        for member in members_result.data or []
        if member.get("user_id")
    })
    if not member_ids:
        logger.error(
            "Cannot notify vendor for approved return request %s: "
            "vendor has no active members.",
            return_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Unable to notify the product vendor.",
        )

    existing_notifications = (
        supabase.table("notifications")
        .select("recipient_id")
        .in_("recipient_id", member_ids)
        .eq("recipient_role", "vendor")
        .eq("notification_type", notification_type)
        .eq("reference_type", "return_request")
        .eq("reference_id", return_id)
        .execute()
    )
    existing_recipient_ids = {
        str(notification["recipient_id"])
        for notification in existing_notifications.data or []
        if notification.get("recipient_id")
    }
    missing_member_ids = [
        member_id
        for member_id in member_ids
        if member_id not in existing_recipient_ids
    ]
    if not missing_member_ids:
        return

    product_name = (
        order_items[0].get("product_name")
        or "an ordered product"
    )
    request_label = "exchange" if is_exchange else "return"
    supabase.table("notifications").insert([
        {
            "recipient_id": member_id,
            "recipient_role": "vendor",
            "title": f"{request_label.title()} request approved",
            "message": (
                f"The {request_label} request for {product_name} "
                "has been approved. Please process the request."
            ),
            "notification_type": notification_type,
            "reference_type": "return_request",
            "reference_id": return_id,
            "is_read": False,
        }
        for member_id in missing_member_ids
    ]).execute()


def notify_customer_return_status(return_request: dict) -> None:
    request_id = return_request.get("id")
    request_type = return_request.get("request_type") or "return"
    is_exchange = request_type == "replacement"
    status_value = return_request.get("status") or "updated"
    request_label = "exchange" if is_exchange else "return"
    status_message = {
        "under_review": "is being reviewed",
        "approved": "has been approved",
        "rejected": "was declined",
        "pickup_scheduled": "has a pickup scheduled",
        "item_received": "has been received",
        "replacement_processing": "is being prepared",
        "refund_processing": "has entered refund processing",
        "completed": "is complete",
        "cancelled": "was cancelled",
    }.get(status_value, status_value.replace("_", " "))

    create_customer_notification(
        customer_id=return_request.get("customer_id"),
        title=f"{request_label.title()} request update",
        message=f"Your {request_label} request {status_message}.",
        notification_type=(
            f"{'exchange' if is_exchange else 'return'}_request_{status_value}"
        ),
        reference_type="return_request",
        reference_id=str(request_id) if request_id else None,
    )


def add_return_request_details(return_requests: list[dict]) -> list[dict]:
    if not return_requests:
        return return_requests

    order_item_ids = sorted({
        str(item["order_item_id"])
        for item in return_requests
        if item.get("order_item_id")
    })
    order_items_by_id = {}

    if order_item_ids:
        order_items_result = (
            supabase.table("order_items")
            .select(
                "id, order_id, product_id, product_name, variant_name, "
                "unit_price, total_price, quantity"
            )
            .in_("id", order_item_ids)
            .execute()
        )
        order_items_by_id = {
            str(item["id"]): item
            for item in order_items_result.data or []
        }

    order_ids = sorted({
        str(value)
        for item in return_requests
        for value in (
            item.get("order_id"),
            order_items_by_id.get(
                str(item.get("order_item_id") or ""),
                {},
            ).get("order_id"),
        )
        if value
    })
    product_ids = sorted({
        str(value)
        for item in return_requests
        for value in (
            item.get("product_id"),
            order_items_by_id.get(
                str(item.get("order_item_id") or ""),
                {},
            ).get("product_id"),
        )
        if value
    })
    customer_ids = sorted({
        str(item["customer_id"])
        for item in return_requests
        if item.get("customer_id")
    })

    orders_by_id = {}
    if order_ids:
        orders_result = (
            supabase.table("orders")
            .select("id, order_number")
            .in_("id", order_ids)
            .execute()
        )
        orders_by_id = {
            str(order["id"]): order
            for order in orders_result.data or []
        }

    products_by_id = {}
    product_images_by_id = {}
    if product_ids:
        products_result = (
            supabase.table("products")
            .select("id, name")
            .in_("id", product_ids)
            .execute()
        )
        products_by_id = {
            str(product["id"]): product
            for product in products_result.data or []
        }

        images_result = (
            supabase.table("product_images")
            .select("product_id, image_url, is_primary, sort_order")
            .in_("product_id", product_ids)
            .execute()
        )
        for image in images_result.data or []:
            product_images_by_id.setdefault(
                str(image["product_id"]),
                [],
            ).append(image)

    customers_by_id = {}
    if customer_ids:
        customers_result = (
            supabase.table("profiles")
            .select("id, full_name")
            .in_("id", customer_ids)
            .execute()
        )
        customers_by_id = {
            str(customer["id"]): customer
            for customer in customers_result.data or []
        }

    for request in return_requests:
        order_item = order_items_by_id.get(
            str(request.get("order_item_id") or ""),
            {},
        )
        order_id = str(
            request.get("order_id") or order_item.get("order_id") or ""
        )
        order = orders_by_id.get(order_id)
        product_id = str(
            request.get("product_id") or order_item.get("product_id") or ""
        )
        product = products_by_id.get(product_id, {})
        images = product_images_by_id.get(product_id, [])
        primary_image = next(
            (
                image
                for image in images
                if image.get("is_primary") and image.get("image_url")
            ),
            None,
        )
        if primary_image is None:
            primary_image = min(
                (
                    image
                    for image in images
                    if image.get("image_url")
                ),
                key=lambda image: int(image.get("sort_order") or 0),
                default=None,
            )

        customer_id = str(request.get("customer_id") or "")
        customer = customers_by_id.get(customer_id)
        product_name = (
            request.get("product_name")
            or order_item.get("product_name")
            or product.get("name")
        )
        product_image_url = (
            request.get("product_image_url")
            or (primary_image or {}).get("image_url")
        )

        request["order_item"] = order_item or None
        request["order"] = order
        request["order_number"] = (
            (order or {}).get("order_number")
            or request.get("order_number")
        )
        request["product"] = {
            "id": product_id or None,
            "name": product_name,
            "image_url": product_image_url,
        }
        request["product_name"] = product_name
        request["product_image_url"] = product_image_url
        request["customer"] = customer
        request["customer_name"] = (
            (customer or {}).get("full_name")
            or request.get("customer_name")
        )
        request["customer_email"] = (
            (customer or {}).get("email")
            or request.get("customer_email")
        )

    return return_requests


@router.get("")
def list_return_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("return_requests").select("*", count="exact")

        if status_filter:
            if status_filter not in ALLOWED_RETURN_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid return status filter.",
                )
            query = query.eq("status", status_filter)

        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        items = add_return_request_details(result.data or [])
        returns_count = (
            supabase.table("return_requests")
            .select("id", count="exact", head=True)
            .eq("request_type", "return")
            .execute()
            .count
            or 0
        )
        exchanges_count = (
            supabase.table("return_requests")
            .select("id", count="exact", head=True)
            .eq("request_type", "replacement")
            .execute()
            .count
            or 0
        )
        pending_count = (
            supabase.table("return_requests")
            .select("id", count="exact", head=True)
            .in_("status", sorted(PENDING_RETURN_STATUSES))
            .execute()
            .count
            or 0
        )

        return {
            "items": items,
            "total": result.count or 0,
            "summary": {
                "returns": returns_count,
                "exchanges": exchanges_count,
                "pending": pending_count,
            },
            "limit": limit,
            "offset": offset,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to list return requests: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve return requests.",
        ) from exc



@router.patch("/{return_id}/status")
def update_return_status(
    return_id: UUID,
    payload: ReturnStatusUpdate,
):
    try:
        # Fetch the current return request.
        existing_result = (
            supabase.table("return_requests")
            .select("*")
            .eq("id", str(return_id))
            .execute()
        )

        existing_rows = (
            existing_result.data if existing_result else None
        ) or []

        existing = existing_rows[0] if existing_rows else None

        if not existing:
            raise HTTPException(
                status_code=404,
                detail="Return request not found.",
            )

        previous_status = existing["status"]
        new_status = payload.status

        # Idempotent response for an unchanged status.
        if previous_status == new_status:
            if new_status == "approved":
                ensure_vendor_approval_notification(existing)
            return {
                "message": "Return request status is unchanged.",
                "return_request": existing,
            }

        allowed = ALLOWED_RETURN_TRANSITIONS.get(previous_status, set())
        if (
            previous_status == "item_received"
            and existing.get("request_type") != "replacement"
        ):
            allowed = {"refund_processing"}

        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid return status transition: "
                    f"{previous_status} -> {new_status}"
                ),
            )

        # Completion is handled by PostgreSQL in one transaction.
        if new_status == "completed":
            rpc_result = supabase.rpc(
                "complete_return_request",
                {
                    "p_return_id": str(return_id),
                    "p_notes": payload.notes,
                },
            ).execute()

            rpc_data = rpc_result.data if rpc_result else None

            if not rpc_data:
                raise HTTPException(
                    status_code=500,
                    detail="Unable to complete return request.",
                )

            # The function returns JSONB containing the updated request.
            if isinstance(rpc_data, dict):
                updated_request = rpc_data.get("return_request")

                if updated_request:
                    notify_customer_return_status(updated_request)
                    return {
                        "message": rpc_data.get(
                            "message",
                            "Return request status updated.",
                        ),
                        "return_request": updated_request,
                    }

                # A repeated completion may return only an ID and status.
                if rpc_data.get("status") == "completed":
                    refreshed_result = (
                        supabase.table("return_requests")
                        .select("*")
                        .eq("id", str(return_id))
                        .execute()
                    )
                    refreshed_rows = (
                        refreshed_result.data
                        if refreshed_result
                        else None
                    ) or []

                    if refreshed_rows:
                        return {
                            "message": rpc_data.get(
                                "message",
                                "Return request is already completed.",
                            ),
                            "return_request": refreshed_rows[0],
                        }

            raise HTTPException(
                status_code=500,
                detail="Unexpected response from return completion function.",
            )

        # Preserve the existing workflow for non-completion transitions.
        update_data = {"status": new_status}

        if payload.notes:
            existing_notes = existing.get("description") or ""
            update_data["description"] = (
                f"{existing_notes}\n{payload.notes}".strip()
            )

        update_result = (
            supabase.table("return_requests")
            .update(update_data)
            .eq("id", str(return_id))
            .eq("status", previous_status)
            .execute()
        )

        updated_rows = (
            update_result.data if update_result else None
        ) or []

        if not updated_rows:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The return request may have changed. "
                    "Refresh it and try again."
                ),
            )

        if new_status == "approved":
            notify_customer_return_status(updated_rows[0])
            ensure_vendor_approval_notification(updated_rows[0])
        else:
            notify_customer_return_status(updated_rows[0])

        return {
            "message": "Return request status updated.",
            "return_request": updated_rows[0],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to update return request: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Unable to update return request.",
        ) from exc

   

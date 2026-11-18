from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase
from app.api.admin.orders import add_order_item_products
from app.api.admin.returns import add_return_request_details
from app.api.admin.support import get_support_ticket


REFERENCE_TABLES = {
    "order": "orders",
    "orders": "orders",
    "payment": "payments",
    "payments": "payments",
    "vendor_payout": "vendor_payouts",
    "vendor_payouts": "vendor_payouts",
    "payout": "vendor_payouts",
    "refund": "refunds",
    "refunds": "refunds",
    "return_request": "return_requests",
    "return_requests": "return_requests",
    "product": "products",
    "products": "products",
    "vendor_product": "products",
    "vendor_products": "products",
    "vendor_product_updated": "products",
    "product_variant": "product_variants",
    "product_variants": "product_variants",
    "shipment": "shipments",
    "shipments": "shipments",
    "support_ticket": "support_tickets",
    "support_tickets": "support_tickets",
    "vendor": "vendors",
    "vendors": "vendors",
}

SENSITIVE_NOTIFICATION_FIELDS = {
    "access_token",
    "refresh_token",
    "token",
    "password",
    "client_secret",
    "secret",
    "api_key",
    "authorization",
    "card_number",
    "cvv",
    "cvc",
    "raw_response",
    "gateway_response",
}


router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin Notifications"],
    dependencies=[Depends(get_current_admin)],
)


def get_admin_id(current_admin):
    return str(current_admin.id)


def sanitize_notification_record(value):
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            field_name = str(key).lower()
            if (
                field_name in SENSITIVE_NOTIFICATION_FIELDS
                or field_name.endswith(("_token", "_secret", "_password"))
                or "authorization" in field_name
            ):
                continue

            safe_item = sanitize_notification_record(item)
            if safe_item is not None:
                sanitized[key] = safe_item
        return sanitized

    if isinstance(value, list):
        return [
            safe_item
            for item in value
            if (safe_item := sanitize_notification_record(item)) is not None
        ]

    if isinstance(value, str) and value.startswith("data:"):
        return None

    return value


def fetch_reference_record(table_name: str, record_id: str):
    result = (
        supabase.table(table_name)
        .select("*")
        .eq("id", str(record_id))
        .maybe_single()
        .execute()
    )
    record = result.data

    if not record:
        return None

    if table_name == "orders":
        return add_order_item_products([record])[0]
    if table_name == "return_requests":
        return add_return_request_details([record])[0]
    if table_name == "support_tickets":
        return get_support_ticket(str(record_id))

    return record


def enrich_related_records(record: dict) -> dict:
    related_records = {}
    relation_fields = (
        ("order_id", "order", "orders"),
        ("customer_id", "customer", "profiles"),
        ("vendor_id", "vendor", "vendors"),
        ("product_id", "product", "products"),
        ("product_variant_id", "product_variant", "product_variants"),
        ("variant_id", "product_variant", "product_variants"),
    )

    for field, relation_name, table_name in relation_fields:
        record_id = record.get(field)
        if not record_id or relation_name in related_records:
            continue

        related_record = fetch_reference_record(table_name, str(record_id))
        if related_record:
            related_records[relation_name] = related_record

    if related_records:
        record["related"] = related_records

    return record


def enrich_notification(
    notification: dict,
    include_vendor: bool = False,
) -> dict:
    reference_type = notification.get("reference_type")
    reference_id = notification.get("reference_id")
    table_name = REFERENCE_TABLES.get(reference_type)
    notification_type = str(
        notification.get("notification_type") or ""
    ).lower()

    if (
        not table_name
        and "product" in notification_type
        and "update" in notification_type
    ):
        table_name = "products"

    if not reference_id or not table_name:
        return notification

    if table_name == "products":
        product_result = (
            supabase.table("products")
            .select("id, name, vendor_id, approval_status, status")
            .eq("id", str(reference_id))
            .maybe_single()
            .execute()
        )
        product = product_result.data

        if not product:
            return notification

        notification["product_id"] = product.get("id")
        notification["product_name"] = product.get("name")
        notification["vendor_id"] = product.get("vendor_id")
        notification["approval_status"] = product.get("approval_status")
        notification["product_status"] = product.get("status")

        if include_vendor and product.get("vendor_id"):
            vendor_result = (
                supabase.table("vendors")
                .select("id, business_name, legal_name")
                .eq("id", str(product["vendor_id"]))
                .maybe_single()
                .execute()
            )
            vendor = vendor_result.data
            if vendor:
                notification["vendor_name"] = (
                    vendor.get("business_name")
                    or vendor.get("legal_name")
                )
        return notification

    record = fetch_reference_record(table_name, str(reference_id))
    if not record:
        return notification

    if table_name == "orders":
        notification["order"] = sanitize_notification_record(record)
        return notification

    if table_name in {"return_requests", "support_tickets"}:
        notification["reference_record"] = sanitize_notification_record(record)
        return notification

    notification["reference_record"] = sanitize_notification_record(
        enrich_related_records(record)
    )
    return notification


@router.get("")
def list_notifications(
    current_admin=Depends(get_current_admin),
    is_read: bool | None = Query(default=None),
    notification_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        admin_id = get_admin_id(current_admin)

        query = (
            supabase.table("notifications")
            .select("*", count="exact")
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
        )

        if is_read is not None:
            query = query.eq("is_read", is_read)

        if notification_type:
            query = query.eq("notification_type", notification_type)

        result = (
            query
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        notifications = result.data or []

        return {
            "items": notifications,
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve notifications",
        ) from exc


@router.get("/unread-count")
def get_unread_count(
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .select("id", count="exact")
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .eq("is_read", False)
            .execute()
        )

        return {
            "unread_count": result.count or 0
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve unread notification count",
        ) from exc


@router.get("/{notification_id}")
def get_notification(
    notification_id: UUID,
    current_admin=Depends(get_current_admin),
):
    try:
        result = (
            supabase.table("notifications")
            .select("*")
            .eq("id", str(notification_id))
            .eq("recipient_id", get_admin_id(current_admin))
            .eq("recipient_role", "admin")
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        return {
            "notification": enrich_notification(
                result.data,
                include_vendor=True,
            )
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve notification",
        ) from exc


@router.patch("/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("id", str(notification_id))
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .select("id, is_read")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        return {
            "message": "Notification marked as read",
            "notification": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update notification",
        ) from exc


@router.patch("/{notification_id}/unread")
def mark_notification_unread(
    notification_id: UUID,
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .update({"is_read": False})
            .eq("id", str(notification_id))
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .select("id, is_read")
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        return {
            "message": "Notification marked as unread",
            "notification": result.data[0],
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to update notification",
        ) from exc


@router.patch("/read-all")
def mark_all_notifications_read(
    current_admin=Depends(get_current_admin),
):
    try:
        admin_id = get_admin_id(current_admin)

        result = (
            supabase.table("notifications")
            .update({"is_read": True})
            .eq("recipient_id", admin_id)
            .eq("recipient_role", "admin")
            .eq("is_read", False)
            .execute()
        )

        return {
            "message": "All notifications marked as read",
            "updated_count": len(result.data or []),
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to mark all notifications as read",
        ) from exc
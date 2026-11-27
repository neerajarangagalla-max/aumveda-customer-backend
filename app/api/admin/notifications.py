from uuid import UUID
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_admin
from app.core.supabase import supabase
from app.api.admin.orders import add_order_item_products
from app.api.admin.returns import add_return_request_details
from app.api.admin.support import get_support_ticket
from app.services.vendor.product_image_service import (
    PRODUCT_IMAGE_BUCKET,
    _public_url_for_path,
)


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
    "product_deletion_request": "product_deletion_requests",
    "product_deletion_requests": "product_deletion_requests",
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
IMAGE_FILE_EXTENSIONS = {
    ".avif",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}
IMAGE_REFERENCE_FIELDS = {
    "image",
    "images",
    "image_url",
    "image_urls",
    "image_path",
    "mobile_image_url",
    "photo",
    "photo_url",
    "photos",
    "thumbnail",
    "thumbnail_url",
    "thumbnails",
}


router = APIRouter(
    prefix="/admin/notifications",
    tags=["Admin Notifications"],
    dependencies=[Depends(get_current_admin)],
)


def get_admin_id(current_admin):
    return str(current_admin.id)


def is_image_reference(field_name: str, value: str) -> bool:
    normalized_field = field_name.lower()
    if normalized_field in IMAGE_REFERENCE_FIELDS:
        return True

    if normalized_field not in {"file_path", "path", "storage_path"}:
        return False

    extension = urlparse(value).path.rsplit(".", 1)
    return (
        len(extension) == 2
        and f".{extension[1].lower()}" in IMAGE_FILE_EXTENSIONS
    )


def public_notification_image_url(value: str) -> str:
    if value.startswith(("http://", "https://", "//", "data:")):
        return value

    path = unquote(urlparse(value).path).lstrip("/")
    storage_marker = (
        f"storage/v1/object/public/{PRODUCT_IMAGE_BUCKET}/"
    )
    if storage_marker in path:
        path = path.split(storage_marker, 1)[1]
    elif path.startswith(f"{PRODUCT_IMAGE_BUCKET}/"):
        path = path[len(PRODUCT_IMAGE_BUCKET) + 1:]

    return _public_url_for_path(path)


def sanitize_notification_record(value, field_name: str | None = None):
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

            safe_item = sanitize_notification_record(item, key)
            if safe_item is not None:
                sanitized[key] = safe_item
        return sanitized

    if isinstance(value, list):
        return [
            safe_item
            for item in value
            if (
                safe_item := sanitize_notification_record(
                    item,
                    field_name,
                )
            ) is not None
        ]

    if isinstance(value, str) and value.startswith("data:"):
        return None

    if (
        isinstance(value, str)
        and field_name
        and is_image_reference(field_name, value)
    ):
        return public_notification_image_url(value)

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

    if table_name == "products":
        images_result = (
            supabase.table("product_images")
            .select("id, image_url, alt_text, is_primary, sort_order")
            .eq("product_id", str(record_id))
            .order("is_primary", desc=True)
            .order("sort_order")
            .execute()
        )
        record["product_images"] = images_result.data or []

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
        ("category_id", "category", "categories"),
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

    product = related_records.get("product")
    if product:
        product_related = {}
        for field, relation_name, table_name in (
            ("vendor_id", "vendor", "vendors"),
            ("category_id", "category", "categories"),
        ):
            record_id = product.get(field)
            if not record_id:
                continue
            related_record = fetch_reference_record(
                table_name,
                str(record_id),
            )
            if related_record:
                product_related[relation_name] = related_record
        if product_related:
            product["related"] = product_related

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
    deletion_text = " ".join(
        str(notification.get(field) or "")
        for field in ("notification_type", "title", "message", "reference_type")
    ).lower()
    is_product_deletion_notification = (
        reference_type in {
            "product_deletion_request",
            "product_deletion_requests",
        }
        or (
            "product" in deletion_text
            and ("deletion" in deletion_text or "delete" in deletion_text)
        )
    )

    if (
        not table_name
        and "product" in deletion_text
        and (
            "update" in deletion_text
            or "revision" in deletion_text
            or "deletion" in deletion_text
            or "delete" in deletion_text
        )
    ):
        table_name = "products"

    if not reference_id or not table_name:
        return notification

    if table_name == "product_deletion_requests":
        request_result = (
            supabase.table("product_deletion_requests")
            .select("*")
            .eq("id", str(reference_id))
            .maybe_single()
            .execute()
        )
        deletion_request = request_result.data

        if not deletion_request:
            request_result = (
                supabase.table("product_deletion_requests")
                .select("*")
                .eq("product_id", str(reference_id))
                .eq("status", "pending")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            requests = request_result.data or []
            deletion_request = requests[0] if requests else None

        if not deletion_request:
            return notification

        notification["deletion_request"] = deletion_request
        reference_id = deletion_request.get("product_id")
        table_name = "products"

    if table_name == "products":
        is_product_revision_notification = (
            reference_type == "vendor_product_updated"
            or (
                "product" in notification_type
                and (
                    "update" in notification_type
                    or "revision" in notification_type
                )
            )
        )
        product_fields = (
            "*, product_variants(*), product_images(*)"
            if is_product_revision_notification
            else "id, name, vendor_id, approval_status, status"
        )
        product_result = (
            supabase.table("products")
            .select(product_fields)
            .eq("id", str(reference_id))
            .maybe_single()
            .execute()
        )
        product = product_result.data

        if not product:
            if is_product_deletion_notification and not notification.get(
                "deletion_request"
            ):
                deletion_result = (
                    supabase.table("product_deletion_requests")
                    .select("*")
                    .eq("id", str(reference_id))
                    .maybe_single()
                    .execute()
                )
                notification["deletion_request"] = deletion_result.data
                if deletion_result.data:
                    reference_id = deletion_result.data.get("product_id")
                    product_result = (
                        supabase.table("products")
                        .select(
                            "id, name, vendor_id, approval_status, status"
                        )
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

        if is_product_deletion_notification:
            deletion_request = notification.get("deletion_request")
            if not deletion_request:
                deletion_result = (
                    supabase.table("product_deletion_requests")
                    .select("*")
                    .eq("product_id", str(reference_id))
                    .eq("status", "pending")
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                requests = deletion_result.data or []
                deletion_request = requests[0] if requests else None
            notification["deletion_request"] = deletion_request

        if is_product_revision_notification:
            revision_result = (
                supabase.table("product_revisions")
                .select("*")
                .eq("product_id", str(reference_id))
                .eq("status", "pending")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            revisions = revision_result.data or []
            if not revisions:
                revision_result = (
                    supabase.table("product_revisions")
                    .select("*")
                    .eq("product_id", str(reference_id))
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                revisions = revision_result.data or []

            notification["current_product"] = product
            notification["revision"] = revisions[0] if revisions else None
            category_ids = {
                str(category_id)
                for category_id in (
                    product.get("category_id"),
                    (revisions[0].get("product_data") or {}).get(
                        "category_id"
                    ) if revisions else None,
                )
                if category_id
            }
            if category_ids:
                category_result = (
                    supabase.table("categories")
                    .select("id, name")
                    .in_("id", list(category_ids))
                    .execute()
                )
                notification["category_names"] = {
                    str(category["id"]): category["name"]
                    for category in (category_result.data or [])
                }

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


def enrich_notification_vendor_names(notifications: list[dict]) -> list[dict]:
    product_reference_types = {
        "product",
        "products",
        "vendor_product",
        "vendor_products",
        "vendor_product_updated",
    }
    product_variant_reference_types = {
        "product_variant",
        "product_variants",
    }
    deletion_reference_types = {
        "product_deletion_request",
        "product_deletion_requests",
    }
    product_ids_by_notification = {}
    product_variant_ids_by_notification = {}
    deletion_ids_by_notification = {}
    vendor_ids_by_notification = {}
    product_ids = set()
    product_variant_ids = set()
    deletion_ids = set()
    all_vendor_ids = set()

    for notification in notifications:
        notification_id = str(notification.get("id") or "")
        reference_type = str(
            notification.get("reference_type") or ""
        ).lower()
        reference_id = str(
            notification.get("reference_id") or ""
        )
        product_id = notification.get("product_id")
        vendor_id = notification.get("vendor_id")

        if product_id:
            product_id = str(product_id)
            product_ids_by_notification[notification_id] = product_id
            product_ids.add(product_id)
        elif reference_type in product_reference_types and reference_id:
            product_ids_by_notification[notification_id] = reference_id
            product_ids.add(reference_id)
        elif (
            reference_type in product_variant_reference_types
            and reference_id
        ):
            product_variant_ids_by_notification[
                notification_id
            ] = reference_id
            product_variant_ids.add(reference_id)
        elif reference_type in deletion_reference_types and reference_id:
            deletion_ids_by_notification[notification_id] = reference_id
            deletion_ids.add(reference_id)
        elif reference_type in {"vendor", "vendors"} and reference_id:
            vendor_id = reference_id

        if vendor_id:
            vendor_id = str(vendor_id)
            vendor_ids_by_notification[notification_id] = vendor_id
            all_vendor_ids.add(vendor_id)

    if product_variant_ids:
        variants_result = (
            supabase.table("product_variants")
            .select("id, product_id")
            .in_("id", list(product_variant_ids))
            .execute()
        )
        variants_by_id = {
            str(variant.get("id")): variant
            for variant in variants_result.data or []
            if variant.get("id")
        }
        for notification_id, variant_id in (
            product_variant_ids_by_notification.items()
        ):
            variant = variants_by_id.get(variant_id)
            if not variant:
                continue
            product_id = variant.get("product_id")
            if product_id:
                product_id = str(product_id)
                product_ids_by_notification[notification_id] = product_id
                product_ids.add(product_id)

    if deletion_ids:
        deletion_result = (
            supabase.table("product_deletion_requests")
            .select("id, product_id")
            .in_("id", list(deletion_ids))
            .execute()
        )
        for request in deletion_result.data or []:
            notification_ids = [
                notification_id
                for notification_id, deletion_id
                in deletion_ids_by_notification.items()
                if deletion_id == str(request.get("id"))
            ]
            product_id = request.get("product_id")
            if not product_id:
                continue
            product_id = str(product_id)
            product_ids.add(product_id)
            for notification_id in notification_ids:
                product_ids_by_notification[notification_id] = product_id

    if product_ids:
        products_result = (
            supabase.table("products")
            .select("id, vendor_id")
            .in_("id", list(product_ids))
            .execute()
        )
        product_vendor_ids = {
            str(product.get("id")): str(product["vendor_id"])
            for product in products_result.data or []
            if product.get("id") and product.get("vendor_id")
        }
        for notification_id, product_id in product_ids_by_notification.items():
            vendor_id = product_vendor_ids.get(product_id)
            if vendor_id:
                vendor_ids_by_notification.setdefault(
                    notification_id,
                    vendor_id,
                )
                all_vendor_ids.add(vendor_id)

    if all_vendor_ids:
        vendors_result = (
            supabase.table("vendors")
            .select("id, business_name, legal_name")
            .in_("id", list(all_vendor_ids))
            .execute()
        )
        vendor_names = {
            str(vendor.get("id")): (
                vendor.get("business_name")
                or vendor.get("legal_name")
            )
            for vendor in vendors_result.data or []
            if vendor.get("id")
        }
        for notification in notifications:
            notification_id = str(notification.get("id") or "")
            vendor_id = vendor_ids_by_notification.get(notification_id)
            vendor_name = vendor_names.get(vendor_id)
            if vendor_name:
                notification["vendor_name"] = vendor_name

    return notifications


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

        notifications = enrich_notification_vendor_names(
            result.data or []
        )

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
        print("ADMIN NOTIFICATION DETAIL ERROR:", repr(exc))
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
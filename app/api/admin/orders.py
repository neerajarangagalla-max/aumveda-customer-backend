from typing import Literal
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.core.security import get_current_admin
from app.core.supabase import supabase
import logging

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/admin/orders",
    tags=["Admin Orders"],
    dependencies=[Depends(get_current_admin)],
)



class OrderStatusUpdate(BaseModel):
    status: Literal[
        "placed",
        "processing",
        "partially_shipped",
        "shipped",
        "delivered",
        "cancelled",
        "returned",
    ]



ALLOWED_ORDER_TRANSITIONS = {
    "placed": {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
    "returned": set(),
}


def add_order_item_products(orders: list[dict]) -> list[dict]:
    if not orders:
        return orders

    order_ids = [
        str(order["id"])
        for order in orders
        if order.get("id")
    ]
    if not order_ids:
        for order in orders:
            order["order_items"] = []
        return orders

    order_items_result = (
        supabase.table("order_items")
        .select(
            "id, order_id, product_id, product_name, variant_name, "
            "quantity, unit_price, total_price"
        )
        .in_("order_id", order_ids)
        .execute()
    )
    order_items = order_items_result.data or []

    product_ids = list({
        str(item["product_id"])
        for item in order_items
        if item.get("product_id")
    })
    products_by_id = {}
    images_by_product_id = {}

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
            images_by_product_id.setdefault(
                str(image["product_id"]),
                [],
            ).append(image)

    items_by_order_id = {}
    for item in order_items:
        product_id = str(item.get("product_id") or "")
        product = products_by_id.get(product_id) or {}
        images = images_by_product_id.get(product_id, [])
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

        item["product_name"] = (
            item.get("product_name") or product.get("name")
        )
        item["image_url"] = (
            primary_image.get("image_url")
            if primary_image
            else None
        )
        items_by_order_id.setdefault(
            str(item.get("order_id")),
            [],
        ).append(item)

    for order in orders:
        order["order_items"] = items_by_order_id.get(
            str(order.get("id")),
            [],
        )

    return orders



@router.get("")
def list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    payment_method_filter: Literal["cod", "online"] | None = Query(
        default=None,
        alias="payment_method",
    ),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    try:
        query = supabase.table("orders").select("*", count="exact")

        if status_filter:
            query = query.eq("status", status_filter)
        if payment_method_filter:
            query = query.eq("payment_method", payment_method_filter)
        if search and search.strip():
            query = query.ilike("order_number", f"%{search.strip()}%")
        result = (
            query.order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        orders = add_order_item_products(result.data or [])

        return {
            "items": orders,
            "total": result.count or 0,
            "limit": limit,
            "offset": offset,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve orders",
        ) from exc


@router.get("/{order_id}")
def get_order(order_id: str):
    try:
        result = (
            supabase.table("orders")
            .select("*")
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Order not found")

        return add_order_item_products([result.data])[0]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve order",
        ) from exc

@router.get("/{order_id}/invoice")
def download_invoice(order_id: str):
    try:
        # Fetch order
        order_result = (
            supabase.table("orders")
            .select(
                "id, order_number, payment_status, currency, "
                "subtotal, shipping, discount, tax, total_amount, created_at"
            )
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )

        order = order_result.data

        if not order:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        # Invoice is available only for paid orders
        if str(order.get("payment_status", "")).lower() != "paid":
            raise HTTPException(
                status_code=400,
                detail="Invoice is available only for successfully paid orders.",
            )

        # Fetch order items
        items_result = (
            supabase.table("order_items")
            .select(
                "id, product_name, variant_name, "
                "quantity, unit_price, total_price"
            )
            .eq("order_id", order_id)
            .execute()
        )

        items = items_result.data or []

        # Generate PDF in memory
        pdf_buffer = BytesIO()
        pdf = canvas.Canvas(pdf_buffer, pagesize=A4)

        width, height = A4
        y = height - 50

        pdf.setFont("Helvetica-Bold", 20)
        pdf.drawString(50, y, "AUMVEDA")

        y -= 30

        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(50, y, "INVOICE")

        y -= 35

        pdf.setFont("Helvetica", 10)
        pdf.drawString(
            50,
            y,
            f"Order Number: {order.get('order_number', '-')}",
        )

        y -= 18

        pdf.drawString(
            50,
            y,
            f"Order Date: {order.get('created_at', '-')}",
        )

        y -= 18

        pdf.drawString(
            50,
            y,
            f"Payment Status: {order.get('payment_status', '-')}",
        )

        y -= 35

        # Table headers
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(50, y, "Product")
        pdf.drawString(300, y, "Qty")
        pdf.drawString(350, y, "Price")
        pdf.drawString(430, y, "Total")

        y -= 20

        pdf.setFont("Helvetica", 9)

        currency = order.get("currency") or "INR"

        for item in items:
            product_name = item.get("product_name") or "-"
            variant_name = item.get("variant_name")

            if variant_name:
                product_name = f"{product_name} - {variant_name}"

            if len(product_name) > 40:
                product_name = product_name[:37] + "..."

            pdf.drawString(50, y, product_name)
            pdf.drawString(
                300,
                y,
                str(item.get("quantity", 0)),
            )
            pdf.drawString(
                350,
                y,
                f"{currency} {float(item.get('unit_price') or 0):.2f}",
            )
            pdf.drawString(
                430,
                y,
                f"{currency} {float(item.get('total_price') or 0):.2f}",
            )

            y -= 18

            if y < 100:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 9)

        y -= 15

        pdf.setFont("Helvetica", 10)

        pdf.drawString(
            350,
            y,
            f"Subtotal: {currency} {float(order.get('subtotal') or 0):.2f}",
        )

        y -= 18

        pdf.drawString(
            350,
            y,
            f"Shipping: {currency} {float(order.get('shipping') or 0):.2f}",
        )

        y -= 18

        pdf.drawString(
            350,
            y,
            f"Discount: {currency} {float(order.get('discount') or 0):.2f}",
        )

        y -= 18

        pdf.drawString(
            350,
            y,
            f"Tax: {currency} {float(order.get('tax') or 0):.2f}",
        )

        y -= 22

        pdf.setFont("Helvetica-Bold", 11)

        pdf.drawString(
            350,
            y,
            f"Total: {currency} {float(order.get('total_amount') or 0):.2f}",
        )

        y -= 40

        pdf.setFont("Helvetica", 10)
        pdf.drawString(
            50,
            y,
            "Thank you for shopping with AUMVEDA.",
        )

        pdf.save()

        pdf_buffer.seek(0)

        filename = (
            f"AUMVEDA-Invoice-{order.get('order_number', order_id)}.pdf"
        )

        return Response(
            content=pdf_buffer.getvalue(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{filename}"'
                )
            },
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to generate invoice: %s", exc)

        raise HTTPException(
            status_code=500,
            detail="Unable to generate invoice",
        ) from exc



@router.patch("/{order_id}/status")
def update_order_status(
    order_id: str,
    payload: OrderStatusUpdate,
    current_admin=Depends(get_current_admin),
):
    try:
        existing = (
            supabase.table("orders")
            .select("id, status")
            .eq("id", order_id)
            .maybe_single()
            .execute()
        )

        if not existing.data:
            raise HTTPException(
                status_code=404,
                detail="Order not found",
            )

        previous_status = existing.data["status"]
        new_status = payload.status

        if previous_status == new_status:
            return {
                "message": "Order status is unchanged",
                "order": existing.data,
            }

        allowed_statuses = ALLOWED_ORDER_TRANSITIONS.get(
            previous_status, set()
        )

        if new_status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid order status transition: "
                    f"{previous_status} -> {new_status}"
                ),
            )

        result = (
            supabase.table("orders")
            .update({"status": new_status})
            .eq("id", order_id)
            .eq("status", previous_status)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=409,
                detail="Order status changed concurrently. Refresh and try again.",
            )

        updated_order = result.data[0]

        try:
            supabase.table("order_status_history").insert(
                {
                    "order_id": order_id,
                    "status": new_status,
                    "changed_by": str(current_admin.id),
                    "notes": (
                        f"Status changed from {previous_status} "
                        f"to {new_status} by admin"
                    ),
                }
            ).execute()

            # Update order items when the entire order is delivered.
            if new_status == "delivered":
                supabase.table("order_items").update(
                    {"status": "delivered"}
                ).eq("order_id", order_id).eq(
                    "status", "pending"
                ).execute()

        except Exception as update_error:
            # Preserve the existing rollback behavior.
            try:
                supabase.table("orders").update(
                    {"status": previous_status}
                ).eq("id", order_id).eq(
                    "status", new_status
                ).execute()
            except Exception:
                logger.exception("Order status rollback failed")

            raise HTTPException(
                status_code=500,
                detail=(
                    "Unable to complete the order status update. "
                    "Please verify the order and its history."
                ),
            ) from update_error

        return {
            "message": "Order status updated and history recorded",
            "order": updated_order,
        }

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("Failed to update order status: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Unable to update order status",
        ) from exc

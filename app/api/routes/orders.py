import logging
from fastapi.responses import Response
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO
from typing import Literal
from uuid import UUID
import time
import httpx

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.supabase import supabase


# ============================================================
# ROUTER
# ============================================================

router = APIRouter(
    prefix="/orders",
    tags=["Orders"],
)

logger = logging.getLogger(__name__)

security = HTTPBearer(
    auto_error=False
)


# ============================================================
# REQUEST MODELS
# ============================================================

class CreateOrderRequest(BaseModel):
    address_id: UUID
    payment_method: Literal["cod", "online"] = "cod"


class CreateBuyNowOrderRequest(BaseModel):
    address_id: UUID
    variant_id: UUID
    quantity: int = Field(ge=1, le=100)
    payment_method: Literal["cod"] = "cod"


# ============================================================
# AUTHENTICATION
# ============================================================

def get_current_customer_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    access_token = credentials.credentials

    try:
        auth_response = (
            supabase
            .auth
            .get_user(access_token)
        )

        user = getattr(
            auth_response,
            "user",
            None,
        )

        user_id = getattr(
            user,
            "id",
            None,
        )

    except Exception as error:
        logger.exception(
            "Supabase access token validation failed: %s",
            str(error),
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={
                "WWW-Authenticate": "Bearer"
            },
        )

    try:
        profile_response = (
            supabase
            .table("profiles")
            .select("id,role,is_active")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )

    except Exception as error:
        logger.exception(
            "Failed to load customer profile: %s",
            str(error),
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to verify customer profile.",
        )

    profiles = profile_response.data or []

    if not profiles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer profile not found.",
        )

    profile = profiles[0]

    if profile.get("role") != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is not a customer account.",
        )

    if profile.get("is_active") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Customer account is inactive.",
        )

    return str(user_id)


# ============================================================
# CREATE CART ORDER
# ============================================================

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
)
def create_order(
    payload: CreateOrderRequest,
    customer_id: str = Depends(get_current_customer_id),
):

    try:
        response = (
            supabase
            .rpc(
                "create_customer_order",
                {
                    "p_customer_id": customer_id,
                    "p_address_id": str(payload.address_id),
                    "p_payment_method": payload.payment_method,
                },
            )
            .execute()
        )

        order = response.data

        if not order:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Order creation returned no data.",
            )

        if isinstance(order, list):
            if not order:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Unable to create order. Please try again.",
                )

            order = order[0]

        create_admin_order_notification(order)

        return {
            "status": "success",
            "message": "Order created successfully.",
            "data": order,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Failed to create order"
        )

        message = str(error)
        lower_message = message.lower()

        if "cart is empty" in lower_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Your cart is empty.",
            )

        if (
            "stock" in lower_message
            or "available" in lower_message
            or "insufficient" in lower_message
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=message,
            )

        if "address" in lower_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected delivery address is invalid.",
            )

        if "payment method" in lower_message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payment method.",
            )

        if (
            "customer profile" in lower_message
            or "customer account" in lower_message
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=message,
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create order: {message}",
        )


# ============================================================
# BUY NOW ORDER
# ============================================================
# Independent COD order.
# Does not read or modify the customer's cart.
# Uses the existing create_buy_now_order RPC.
# ============================================================

@router.post(
    "/buy-now",
    status_code=status.HTTP_201_CREATED,
)
def create_buy_now_order(
    payload: CreateBuyNowOrderRequest,
    customer_id: str = Depends(get_current_customer_id),
):

    try:
        response = (
            supabase
            .rpc(
                "create_buy_now_order",
                {
                    "p_customer_id": customer_id,
                    "p_address_id": str(payload.address_id),
                    "p_variant_id": str(payload.variant_id),
                    "p_quantity": payload.quantity,
                    "p_payment_method": "cod",
                },
            )
            .execute()
        )

        order = response.data

        if isinstance(order, list):
            order = order[0] if order else None

        if (
            not isinstance(order, dict)
            or order.get("success") is not True
            or not order.get("order_id")
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Buy Now order was not confirmed.",
            )

        # Notify admin after successful Buy Now order.
        # The RPC returns order_id, so fetch the created order
        # before creating the admin notification.
        try:
            order_response = (
                supabase
                .table("orders")
                .select("*")
                .eq("id", str(order["order_id"]))
                .limit(1)
                .execute()
            )

            created_order = (
                order_response.data[0]
                if order_response.data
                else None
            )

            if created_order:
                create_admin_order_notification(created_order)

        except Exception:
            # Notification failure must never fail the order.
            logger.exception(
                "Failed to create admin notification for Buy Now order."
            )

        return {
            "status": "success",
            "message": "Buy Now order created successfully.",
            "data": order,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception(
            "Buy Now order creation failed."
        )

        message = str(error)
        lower_message = message.lower()

        if any(
            value in lower_message
            for value in (
                "insufficient stock",
                "unable to reserve inventory",
                "unavailable",
                "variant not found",
                "invalid product price",
                "stock",
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The selected product is unavailable "
                    "or has insufficient stock."
                ),
            )

        if any(
            value in lower_message
            for value in (
                "invalid delivery address",
                "missing required order information",
                "address",
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid delivery address or order information.",
            )

        if any(
            value in lower_message
            for value in (
                "quantity",
                "payment method",
                "cash on delivery",
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid quantity or payment method.",
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create Buy Now order.",
        )


# ============================================================
# GET ORDERS
# ============================================================

@router.get("")
def get_orders(
    customer_id: str = Depends(get_current_customer_id),
):

    try:
        # 1. Get all orders belonging to this customer.
        response = (
            supabase
            .table("orders")
            .select("*")
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .execute()
        )

        orders = response.data or []

        if not orders:
            return {
                "status": "success",
                "count": 0,
                "data": [],
            }

        # 2. Fetch all items belonging to these orders.
        order_ids = [
            order["id"]
            for order in orders
        ]

        items_response = (
            supabase
            .table("order_items")
            .select("*")
            .in_("order_id", order_ids)
            .execute()
        )

        order_items = items_response.data or []

        # 3. Collect product and variant IDs.
        product_ids = list({
            item["product_id"]
            for item in order_items
            if item.get("product_id")
        })

        variant_ids = list({
            item["variant_id"]
            for item in order_items
            if item.get("variant_id")
        })

        # 4. Fetch product details.
        products = []

        if product_ids:
            products_response = (
                supabase
                .table("products")
                .select("*")
                .in_("id", product_ids)
                .execute()
            )

            products = products_response.data or []

        # 5. Fetch variant details.
        variants = []

        if variant_ids:
            variants_response = (
                supabase
                .table("product_variants")
                .select("*")
                .in_("id", variant_ids)
                .execute()
            )

            variants = variants_response.data or []

        # 6. Fetch product images.
        product_images = []

        if product_ids:
            images_response = (
                supabase
                .table("product_images")
                .select("*")
                .in_("product_id", product_ids)
                .execute()
            )

            product_images = images_response.data or []

        images_by_product_id = {}

        for image in product_images:
            product_id = str(
                image.get("product_id")
            )

            images_by_product_id.setdefault(
                product_id,
                []
            ).append(image)

        for product in products:
            images = images_by_product_id.get(
                str(product["id"]),
                []
            )

            product["product_images"] = images

            primary_image = next(
                (
                    image
                    for image in images
                    if image.get("is_primary")
                ),
                None,
            )

            if primary_image:
                product["image_url"] = (
                    primary_image.get("image_url")
                    or primary_image.get("url")
                )

        # 7. Create lookup dictionaries.
        products_by_id = {
            product["id"]: product
            for product in products
        }

        variants_by_id = {
            variant["id"]: variant
            for variant in variants
        }

        # 8. Attach products and variants to order items.
        items_by_order = {}

        for item in order_items:

            item["product"] = products_by_id.get(
                item.get("product_id")
            )

            item["variant"] = variants_by_id.get(
                item.get("variant_id")
            )

            order_id = item["order_id"]

            if order_id not in items_by_order:
                items_by_order[order_id] = []

            items_by_order[order_id].append(item)

        # 9. Attach items to every order.
        for order in orders:
            order["items"] = items_by_order.get(
                order["id"],
                []
            )

        return {
            "status": "success",
            "count": len(orders),
            "data": orders,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to load customer orders"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load orders.",
        )


# ============================================================
# SUPABASE READ WITH RETRIES
# ============================================================

def execute_supabase_read(
    query,
    retries=3,
):

    for attempt in range(retries):

        try:
            return query.execute()

        except (
            httpx.ReadError,
            httpx.ConnectError,
            httpx.TimeoutException,
        ):

            if attempt == retries - 1:
                raise

            delay = 0.5 * (2 ** attempt)

            logger.warning(
                "Supabase read failed; retrying in %s seconds "
                "(attempt %s/%s)",
                delay,
                attempt + 1,
                retries,
            )

            time.sleep(delay)


# ============================================================
# BUY AGAIN
# ============================================================

@router.get("/buy-again")
def get_buy_again_products(
    customer_id: str = Depends(get_current_customer_id),
):

    try:
        orders_response = (
            supabase
            .table("orders")
            .select("id, created_at")
            .eq("customer_id", customer_id)
            .eq("status", "delivered")
            .order("created_at", desc=True)
            .execute()
        )

        orders = orders_response.data or []

        if not orders:
            return {
                "status": "success",
                "count": 0,
                "data": [],
            }

        order_ids = [
            order["id"]
            for order in orders
        ]

        items_response = (
            supabase
            .table("order_items")
            .select(
                "id, order_id, product_id, variant_id, "
                "product_name, variant_name, quantity, "
                "unit_price, total_price, created_at"
            )
            .in_("order_id", order_ids)
            .execute()
        )

        order_items = items_response.data or []

        if not order_items:
            return {
                "status": "success",
                "count": 0,
                "data": [],
            }

        product_ids = list({
            item["product_id"]
            for item in order_items
            if item.get("product_id")
        })

        variant_ids = list({
            item["variant_id"]
            for item in order_items
            if item.get("variant_id")
        })

        products = []

        if product_ids:
            products_response = (
                supabase
                .table("products")
                .select("*")
                .in_("id", product_ids)
                .execute()
            )

            products = products_response.data or []

        variants = []

        if variant_ids:
            variants_response = (
                supabase
                .table("product_variants")
                .select("*")
                .in_("id", variant_ids)
                .execute()
            )

            variants = variants_response.data or []

        product_images = []

        if product_ids:
            images_response = (
                supabase
                .table("product_images")
                .select("*")
                .in_("product_id", product_ids)
                .execute()
            )

            product_images = images_response.data or []

        images_by_product_id = {}

        for image in product_images:
            product_id = str(
                image.get("product_id")
            )

            images_by_product_id.setdefault(
                product_id,
                []
            ).append(image)

        for product in products:

            product["product_images"] = (
                images_by_product_id.get(
                    str(product["id"]),
                    [],
                )
            )

            primary_image = next(
                (
                    image
                    for image in product["product_images"]
                    if image.get("is_primary")
                ),
                None,
            )

            if primary_image:
                product["image_url"] = (
                    primary_image.get("image_url")
                    or primary_image.get("url")
                )

            elif product["product_images"]:

                first_image = (
                    product["product_images"][0]
                )

                product["image_url"] = (
                    first_image.get("image_url")
                    or first_image.get("url")
                )

        products_by_id = {
            str(product["id"]): product
            for product in products
        }

        variants_by_id = {
            str(variant["id"]): variant
            for variant in variants
        }

        buy_again = {}

        for item in order_items:

            product_id = item.get("product_id")

            if not product_id:
                continue

            product = products_by_id.get(
                str(product_id)
            )

            if not product:
                continue

            variant = variants_by_id.get(
                str(item.get("variant_id"))
            )

            key = (
                f"{product_id}:"
                f"{item.get('variant_id') or 'default'}"
            )

            if key not in buy_again:

                buy_again[key] = {
                    "product": product,
                    "variant": variant,
                    "last_purchased_at": item.get(
                        "created_at"
                    ),
                    "last_order_id": item.get(
                        "order_id"
                    ),
                    "total_quantity_purchased": 0,
                    "purchase_count": 0,
                    "last_purchase_price": item.get(
                        "unit_price"
                    ),
                }

            buy_again[key][
                "total_quantity_purchased"
            ] += item.get("quantity") or 0

            buy_again[key][
                "purchase_count"
            ] += 1

        results = sorted(
            buy_again.values(),
            key=lambda item:
                item.get("last_purchased_at") or "",
            reverse=True,
        )

        return {
            "status": "success",
            "count": len(results),
            "data": results,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to load Buy Again products"
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Unable to load previously purchased "
                "products."
            ),
        )


# ============================================================
# DOWNLOAD CUSTOMER INVOICE
# ============================================================

@router.get("/{order_id}/invoice")
def download_invoice(
    order_id: UUID,
    customer_id: str = Depends(get_current_customer_id),
):

    try:

        response = execute_supabase_read(
            supabase
            .table("orders")
            .select(
                """
                id,
                order_number,
                customer_id,
                status,
                payment_method,
                payment_status,
                currency,
                subtotal,
                shipping,
                discount,
                tax,
                total_amount,
                created_at
                """
            )
            .eq("id", str(order_id))
            .eq("customer_id", customer_id)
            .limit(1)
        )

        orders = response.data or []

        if not orders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        order = orders[0]

        if str(
            order.get("payment_status", "")
        ).lower() != "paid":

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Invoice is available only for "
                    "successfully paid orders."
                ),
            )

        items_response = execute_supabase_read(
            supabase
            .table("order_items")
            .select(
                """
                id,
                product_name,
                variant_name,
                quantity,
                unit_price,
                total_price
                """
            )
            .eq("order_id", str(order_id))
        )

        order_items = items_response.data or []

        pdf_buffer = BytesIO()

        pdf = canvas.Canvas(
            pdf_buffer,
            pagesize=A4,
        )

        page_width, page_height = A4

        left_margin = 40
        right_margin = page_width - 40
        y = page_height - 50

        currency = order.get("currency") or "INR"

        def money(value):
            try:
                return (
                    f"{currency} "
                    f"{float(value or 0):,.2f}"
                )
            except (TypeError, ValueError):
                return f"{currency} 0.00"

        def draw_text(
            text,
            x,
            y_position,
            size=10,
        ):
            pdf.setFont(
                "Helvetica",
                size,
            )

            pdf.drawString(
                x,
                y_position,
                str(text),
            )

        pdf.setFont(
            "Helvetica-Bold",
            20,
        )

        pdf.drawString(
            left_margin,
            y,
            "AUMVEDA",
        )

        y -= 28

        pdf.setFont(
            "Helvetica-Bold",
            16,
        )

        pdf.drawString(
            left_margin,
            y,
            "INVOICE",
        )

        y -= 35

        draw_text(
            f"Order Number: "
            f"{order.get('order_number') or str(order_id)}",
            left_margin,
            y,
        )

        y -= 18

        draw_text(
            f"Order Date: "
            f"{order.get('created_at') or '-'}",
            left_margin,
            y,
        )

        y -= 18

        draw_text(
            f"Payment Status: "
            f"{order.get('payment_status') or '-'}",
            left_margin,
            y,
        )

        y -= 30

        pdf.setFont(
            "Helvetica-Bold",
            10,
        )

        pdf.drawString(
            left_margin,
            y,
            "Product",
        )

        pdf.drawString(
            330,
            y,
            "Qty",
        )

        pdf.drawString(
            380,
            y,
            "Price",
        )

        pdf.drawString(
            470,
            y,
            "Total",
        )

        y -= 8

        pdf.line(
            left_margin,
            y,
            right_margin,
            y,
        )

        y -= 18

        pdf.setFont(
            "Helvetica",
            9,
        )

        for item in order_items:

            product_name = (
                item.get("product_name")
                or "Product"
            )

            variant_name = item.get(
                "variant_name"
            )

            if variant_name:
                product_name = (
                    f"{product_name} - "
                    f"{variant_name}"
                )

            if len(product_name) > 48:
                product_name = (
                    product_name[:45] + "..."
                )

            quantity = (
                item.get("quantity") or 0
            )

            unit_price = (
                item.get("unit_price") or 0
            )

            total_price = item.get(
                "total_price"
            )

            if total_price is None:
                try:
                    total_price = (
                        float(unit_price)
                        * int(quantity)
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    total_price = 0

            pdf.drawString(
                left_margin,
                y,
                str(product_name),
            )

            pdf.drawRightString(
                350,
                y,
                str(quantity),
            )

            pdf.drawRightString(
                455,
                y,
                money(unit_price),
            )

            pdf.drawRightString(
                right_margin,
                y,
                money(total_price),
            )

            y -= 18

            if y < 100:

                pdf.showPage()

                y = page_height - 50

                pdf.setFont(
                    "Helvetica-Bold",
                    10,
                )

                pdf.drawString(
                    left_margin,
                    y,
                    "Product",
                )

                pdf.drawString(
                    330,
                    y,
                    "Qty",
                )

                pdf.drawString(
                    380,
                    y,
                    "Price",
                )

                pdf.drawString(
                    470,
                    y,
                    "Total",
                )

                y -= 20

                pdf.setFont(
                    "Helvetica",
                    9,
                )

        y -= 10

        pdf.line(
            left_margin,
            y,
            right_margin,
            y,
        )

        y -= 25

        summary_x = 360
        value_x = right_margin

        pdf.setFont(
            "Helvetica",
            10,
        )

        pdf.drawString(
            summary_x,
            y,
            "Subtotal",
        )

        pdf.drawRightString(
            value_x,
            y,
            money(order.get("subtotal")),
        )

        y -= 18

        pdf.drawString(
            summary_x,
            y,
            "Shipping",
        )

        pdf.drawRightString(
            value_x,
            y,
            money(order.get("shipping")),
        )

        y -= 18

        pdf.drawString(
            summary_x,
            y,
            "Discount",
        )

        pdf.drawRightString(
            value_x,
            y,
            money(order.get("discount")),
        )

        y -= 18

        pdf.drawString(
            summary_x,
            y,
            "Tax",
        )

        pdf.drawRightString(
            value_x,
            y,
            money(order.get("tax")),
        )

        y -= 24

        pdf.setFont(
            "Helvetica-Bold",
            11,
        )

        pdf.drawString(
            summary_x,
            y,
            "Total",
        )

        pdf.drawRightString(
            value_x,
            y,
            money(order.get("total_amount")),
        )

        y -= 45

        pdf.setFont(
            "Helvetica",
            10,
        )

        pdf.drawString(
            left_margin,
            y,
            "Thank you for shopping with AUMVEDA.",
        )

        pdf.save()

        pdf_buffer.seek(0)

        filename = (
            f"invoice-"
            f"{order.get('order_number') or str(order_id)}"
            f".pdf"
        )

        return Response(
            content=pdf_buffer.getvalue(),
            media_type="application/pdf",
            headers={
                "Content-Disposition":
                    f'attachment; filename="{filename}"'
            },
        )

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "Failed to generate customer invoice: "
            "order_id=%s customer_id=%s",
            order_id,
            customer_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Failed to generate invoice. "
                "Please try again."
            ),
        )


# ============================================================
# GET SINGLE ORDER
# ============================================================

@router.get("/{order_id}")
def get_order(
    order_id: UUID,
    customer_id: str = Depends(get_current_customer_id),
):

    try:

        logger.info(
            "GET ORDER: Fetching order %s",
            order_id,
        )

        response = execute_supabase_read(
            supabase
            .table("orders")
            .select(
                """
                id,
                order_number,
                customer_id,
                shipping_address_id,
                shipping_address,
                billing_address,
                status,
                payment_method,
                payment_status,
                currency,
                subtotal,
                shipping,
                discount,
                tax,
                total_amount,
                customer_notes,
                created_at,
                updated_at
                """
            )
            .eq("id", str(order_id))
            .eq("customer_id", customer_id)
            .limit(1)
        )

        orders = response.data or []

        if not orders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        order = orders[0]

        items_response = execute_supabase_read(
            supabase
            .table("order_items")
            .select("*")
            .eq("order_id", str(order_id))
        )

        order_items = items_response.data or []

        product_ids = list({
            item["product_id"]
            for item in order_items
            if item.get("product_id")
        })

        variant_ids = list({
            item["variant_id"]
            for item in order_items
            if item.get("variant_id")
        })

        products = []

        if product_ids:
            products_response = execute_supabase_read(
                supabase
                .table("products")
                .select(
                    "*, product_images(*)"
                )
                .in_("id", product_ids)
            )

            products = (
                products_response.data or []
            )

        variants = []

        if variant_ids:
            variants_response = (
                execute_supabase_read(
                    supabase
                    .table("product_variants")
                    .select("*")
                    .in_("id", variant_ids)
                )
            )

            variants = (
                variants_response.data or []
            )

        products_by_id = {
            str(product["id"]): product
            for product in products
        }

        variants_by_id = {
            str(variant["id"]): variant
            for variant in variants
        }

        for item in order_items:

            product = products_by_id.get(
                str(item.get("product_id"))
            )

            if product:

                product_images = (
                    product.get(
                        "product_images"
                    ) or []
                )

                primary_image = next(
                    (
                        image
                        for image in product_images
                        if image.get("is_primary")
                        is True
                    ),
                    None,
                )

                selected_image = (
                    primary_image
                    or (
                        product_images[0]
                        if product_images
                        else None
                    )
                )

                image_url = (
                    selected_image.get("image_url")
                    if selected_image
                    else None
                )

                product["image_url"] = image_url
                item["image_url"] = image_url

            else:
                item["image_url"] = None

            item["product"] = product

            item["variant"] = (
                variants_by_id.get(
                    str(item.get("variant_id"))
                )
            )

        order["items"] = order_items

        logger.info(
            "GET ORDER: Completed successfully"
        )

        return {
            "status": "success",
            "data": order,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "GET ORDER FAILED: "
            "order_id=%s customer_id=%s",
            order_id,
            customer_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Failed to load order details. "
                "Please try again."
            ),
        )


# ============================================================
# CREATE ADMIN NOTIFICATION
# ============================================================

def create_admin_order_notification(
    order: dict,
):

    try:

        admins_response = (
            supabase
            .table("profiles")
            .select("id")
            .eq("role", "admin")
            .eq("is_active", True)
            .execute()
        )

        admins = (
            admins_response.data or []
        )

        if not admins:

            logger.warning(
                "No active admin accounts found "
                "for order notification."
            )

            return

        order_id = order.get("id")

        order_number = (
            order.get("order_number")
            or str(order_id)
        )

        notifications = []

        for admin in admins:

            notifications.append({
                "recipient_id": admin["id"],
                "recipient_role": "admin",
                "title": "New Order Received",
                "message": (
                    f"New order "
                    f"{order_number} has been placed."
                ),
                "notification_type": "new_order",
                "reference_type": "order",
                "reference_id": order_id,
                "is_read": False,
            })

        if notifications:

            supabase.table(
                "notifications"
            ).insert(
                notifications
            ).execute()

            logger.info(
                "Admin order notification created "
                "for order %s",
                order_number,
            )

    except Exception:

        # Notification failure must never
        # interrupt order creation.
        logger.exception(
            "Failed to create admin notification "
            "for new order."
        )
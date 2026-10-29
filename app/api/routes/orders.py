import logging
import time
import httpx
from typing import Literal
from uuid import UUID

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

from pydantic import BaseModel

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
# REQUEST MODEL
# ============================================================

class CreateOrderRequest(BaseModel):
    address_id: UUID
    payment_method: Literal["cod", "online"] = "cod"


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
# CREATE ORDER
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

        # Return an empty list if the customer has no orders.
        if not orders:
            return {
                "status": "success",
                "count": 0,
                "data": [],
            }

        # 2. Fetch all items belonging to these orders.
        order_ids = [order["id"] for order in orders]

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

        # 4. Fetch product details, including available image fields.
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

        # 6. Create lookup dictionaries.
        products_by_id = {
            product["id"]: product
            for product in products
        }

        variants_by_id = {
            variant["id"]: variant
            for variant in variants
        }

        # 7. Attach products and variants to each order item.
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

        # 8. Attach items to every order.
        for order in orders:
            order["items"] = items_by_order.get(
                order["id"], []
            )

        return {
            "status": "success",
            "count": len(orders),
            "data": orders,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Failed to load customer orders")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load orders.",
            )

# ============================================================
# GET SINGLE ORDER
# ============================================================


def execute_supabase_read(query, retries=3):
    for attempt in range(retries):
        try:
            return query.execute()
        except (httpx.ReadError, httpx.ConnectError, httpx.TimeoutException):
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



@router.get("/{order_id}")
def get_order(
    order_id: UUID,
    customer_id: str = Depends(get_current_customer_id),
):
    try:
        logger.info("GET ORDER: Fetching order %s", order_id)

        response = (
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
            .execute()
        )

        logger.info("GET ORDER: Order query succeeded")

        orders = response.data or []

        if not orders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        order = orders[0]

        logger.info("GET ORDER: Fetching order items")

        items_response = (
            supabase
            .table("order_items")
            .select("*")
            .eq("order_id", str(order_id))
            .execute()
        )

        order_items = items_response.data or []

        logger.info(
            "GET ORDER: Loaded %s order items",
            len(order_items),
        )

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
            logger.info("GET ORDER: Fetching products")

            products_response = (
                supabase
                .table("products")
                .select("*, product_images(*)")
                .in_("id", product_ids)
                .execute()
            )

            products = products_response.data or []

            logger.info(
                "GET ORDER: Loaded %s products",
                len(products),
            )

        variants = []

        if variant_ids:
            logger.info("GET ORDER: Fetching variants")

            variants_response = (
                execute_supabase_read(
                    supabase
                    .table("product_variants")
                    .select("*")
                    .in_("id", variant_ids)
                )
            )

            variants = variants_response.data or []

            logger.info(
                "GET ORDER: Loaded %s variants",
                len(variants),
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
            item["product"] = products_by_id.get(
                str(item.get("product_id"))
            )

            item["variant"] = variants_by_id.get(
                str(item.get("variant_id"))
            )

        order["items"] = order_items

        logger.info("GET ORDER: Completed successfully")

        return {
            "status": "success",
            "data": order,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception(
            "GET ORDER FAILED: order_id=%s customer_id=%s",
            order_id,
            customer_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load order details. Please try again.",
        )

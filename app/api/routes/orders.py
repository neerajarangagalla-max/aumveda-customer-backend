import logging

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
                    detail="Order creation returned no data.",
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
                shipping_amount,
                discount_amount,
                tax_amount,
                total_amount,
                customer_notes,
                created_at,
                updated_at
                """
            )
            .eq("customer_id", customer_id)
            .order("created_at", desc=True)
            .execute()
        )

        orders = response.data or []

        return {
            "status": "success",
            "count": len(orders),
            "data": orders,
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Failed to load customer orders")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load orders: {str(error)}",
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
                shipping_amount,
                discount_amount,
                tax_amount,
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

        orders = response.data or []
        if not orders:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )

        return {
            "status": "success",
            "data": orders[0],
        }

    except HTTPException:
        raise

    except Exception as error:
        logger.exception("Failed to load order")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load order: {str(error)}",
        )

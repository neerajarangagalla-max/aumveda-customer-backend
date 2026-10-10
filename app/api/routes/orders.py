import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.schemas.order import CreateOrder
from app.services.order_service import (
    create_order,
    get_order,
    get_orders,
)

router = APIRouter(prefix="/orders", tags=["Orders"])
logger = logging.getLogger(__name__)


@router.get("")
async def orders(user=Depends(get_current_user)):
    try:
        data = get_orders(user.id)

        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }

    except Exception:
        logger.exception("Orders retrieval failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve orders.",
        )


@router.get("/{order_id}")
async def order(
    order_id: str,
    user=Depends(get_current_user),
):
    try:
        data = get_order(user.id, order_id)

        if not data:
            raise HTTPException(
                status_code=404,
                detail="Order not found.",
            )

        return {
            "status": "success",
            "data": data,
        }

    except HTTPException:
        raise

    except Exception:
        logger.exception("Single order lookup failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve order.",
        )


@router.post("")
async def create_order_route(
    payload: CreateOrder,
    user=Depends(get_current_user),
):
    try:
        data = create_order(
            user.id,
            payload.model_dump(),
        )

        return {
            "status": "success",
            "data": data,
        }

    except Exception as e:
        logger.exception("Order creation failed")

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.schemas.cart import AddCartItem, UpdateCartItem
from app.services.cart_service import (
    add_item,
    get_cart,
    remove_item,
    update_item,
)

router = APIRouter(prefix="/cart", tags=["Cart"])
logger = logging.getLogger(__name__)


@router.get("")
async def cart(user=Depends(get_current_user)):
    try:
        data = get_cart(user.id)
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Cart retrieval failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve cart.",
        )


@router.post("/items")
async def add_cart_item(payload: AddCartItem, user=Depends(get_current_user)):
    try:
        data = add_item(
            user.id,
            payload.product_id,
            payload.variant_id,
            payload.quantity,
        )
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Add to cart failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to add item to cart.",
        )


@router.patch("/items/{item_id}")
async def update_cart_item(
    item_id: str,
    payload: UpdateCartItem,
    user=Depends(get_current_user),
):
    try:
        data = update_item(item_id, payload.quantity)
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Cart update failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to update cart item.",
        )


@router.delete("/items/{item_id}")
async def remove_cart_item(item_id: str, user=Depends(get_current_user)):
    try:
        data = remove_item(item_id)
        return {
            "status": "success",
            "data": data,
        }
    except Exception:
        logger.exception("Cart item removal failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to remove cart item.",
        )

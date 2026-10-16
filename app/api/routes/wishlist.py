from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.services.wishlist_service import (
    add_to_wishlist,
    remove_from_wishlist,
    is_product_in_wishlist,
    get_customer_wishlist,
)

router = APIRouter(
    prefix="/wishlist",
    tags=["Wishlist"],
)


@router.get("")
async def get_wishlist(
    user=Depends(get_current_user),
):
    try:
        products = get_customer_wishlist(user.id)

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@router.post("/{product_id}")
async def add_product_to_wishlist(
    product_id: str,
    user=Depends(get_current_user),
):
    try:
        item = add_to_wishlist(
            customer_id=user.id,
            product_id=product_id,
        )

        return {
            "status": "success",
            "message": "Product added to wishlist",
            "data": item,
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@router.delete("/{product_id}")
async def delete_product_from_wishlist(
    product_id: str,
    user=Depends(get_current_user),
):
    try:
        removed = remove_from_wishlist(
            customer_id=user.id,
            product_id=product_id,
        )

        return {
            "status": "success",
            "message": (
                "Product removed from wishlist"
                if removed
                else "Product was not in wishlist"
            ),
            "data": {
                "removed": removed,
                "product_id": product_id,
            },
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


@router.get("/{product_id}/status")
async def get_wishlist_status(
    product_id: str,
    user=Depends(get_current_user),
):
    try:
        wishlisted = is_product_in_wishlist(
            customer_id=user.id,
            product_id=product_id,
        )

        return {
            "status": "success",
            "data": {
                "product_id": product_id,
                "wishlisted": wishlisted,
            },
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )
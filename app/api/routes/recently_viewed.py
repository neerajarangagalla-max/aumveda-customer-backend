import logging

from fastapi import APIRouter, HTTPException, Depends

from app.core.security import get_current_user
from app.services.recently_viewed_service import (
    record_product_view,
    get_recently_viewed_products,
)

router = APIRouter(
    prefix="/recently-viewed",
    tags=["Recently Viewed"],
)

logger = logging.getLogger(__name__)


# ============================================================
# POST - RECORD PRODUCT VIEW
# ============================================================

@router.post("/{product_id}")
async def create_recently_viewed(
    product_id: str,
    user=Depends(get_current_user),
):
    try:

        # ----------------------------------------------------
        # Authenticated user
        # ----------------------------------------------------

        customer_id = user.id

        if not customer_id:
            raise HTTPException(
                status_code=401,
                detail="Unable to identify authenticated customer.",
            )

        # ----------------------------------------------------
        # Validate product ID
        # ----------------------------------------------------

        if not product_id:
            raise HTTPException(
                status_code=400,
                detail="Product ID is required.",
            )

        # ----------------------------------------------------
        # Record product view
        # ----------------------------------------------------

        result = record_product_view(
            customer_id=str(customer_id),
            product_id=str(product_id),
        )

        return {
            "status": "success",
            "message": "Product view recorded successfully.",
            "data": result,
        }

    except HTTPException:
        raise

    except Exception as error:

        logger.exception(
            "Failed to record recently viewed product"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to record product view.",
        ) from error


# ============================================================
# GET - RECENTLY VIEWED PRODUCTS
# ============================================================

@router.get("")
async def get_recently_viewed(
    user=Depends(get_current_user),
):
    try:

        # ----------------------------------------------------
        # Authenticated user
        # ----------------------------------------------------

        customer_id = user.id

        if not customer_id:
            raise HTTPException(
                status_code=401,
                detail="Unable to identify authenticated customer.",
            )

        # ----------------------------------------------------
        # Fetch recently viewed products
        # ----------------------------------------------------

        products = get_recently_viewed_products(
            customer_id=str(customer_id),
            limit=10,
        )

        return {
            "status": "success",
            "count": len(products),
            "data": products,
        }

    except HTTPException:
        raise

    except Exception as error:

        logger.exception(
            "Failed to get recently viewed products"
        )

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve recently viewed products.",
        ) from error
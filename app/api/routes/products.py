import logging

from fastapi import APIRouter, HTTPException

from app.services.product_service import (
    get_product_by_slug,
    get_products,
    get_related_products,
)

router = APIRouter(prefix="/products", tags=["Products"])
logger = logging.getLogger(__name__)


@router.get("")
async def products(
    search: str | None = None,
    category_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    try:
        data = get_products(
            search=search,
            category_id=category_id,
            limit=limit,
            offset=offset,
        )
        return {
            "status": "success",
            "count": len(data),
            "data": data,
        }
    except Exception:
        logger.exception("Product listing failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve products.",
        )


@router.get("/{slug}")
async def product(slug: str):
    try:
        data = get_product_by_slug(slug)
        if not data:
            raise HTTPException(
                status_code=404,
                detail="Product not found.",
            )

        related = get_related_products(data["id"], limit=6)

        return {
            "status": "success",
            "data": {
                **data,
                "related_products": related,
            },
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Single product lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve product.",
        )
